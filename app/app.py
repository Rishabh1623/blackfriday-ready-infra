import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
import psycopg2
import psycopg2.pool
import redis
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ── Configuration ──────────────────────────────────────────────────────────────

RDS_PROXY_ENDPOINT = os.environ["RDS_PROXY_ENDPOINT"]
ELASTICACHE_ENDPOINT = os.environ["ELASTICACHE_ENDPOINT"]
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

PRODUCT_CACHE_TTL = 300  # seconds

# ── Connection pools ───────────────────────────────────────────────────────────

db_pool: psycopg2.pool.ThreadedConnectionPool = None
redis_client: redis.Redis = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, redis_client

    db_pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=0,
        maxconn=50,
        host=RDS_PROXY_ENDPOINT,
        port=5432,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=5,
        sslmode="require",
    )

    redis_client = redis.Redis(
        host=ELASTICACHE_ENDPOINT,
        port=6379,
        ssl=True,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )

    yield

    db_pool.closeall()


app = FastAPI(title="BlackFriday API", lifespan=lifespan)

# ── Middleware ─────────────────────────────────────────────────────────────────


@app.middleware("http")
async def timing_logger(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(
        f"method={request.method} path={request.url.path} "
        f"status={response.status_code} duration_ms={elapsed_ms:.1f}",
        flush=True,
    )
    return response


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_instance_id() -> str:
    """Fetch EC2 instance ID via IMDSv2."""
    try:
        with httpx.Client(timeout=1.0) as client:
            token_resp = client.put(
                "http://169.254.169.254/latest/api/token",
                headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            )
            token = token_resp.text
            id_resp = client.get(
                "http://169.254.169.254/latest/meta-data/instance-id",
                headers={"X-aws-ec2-metadata-token": token},
            )
            return id_resp.text
    except Exception:
        return "local"


def _db_conn():
    for attempt in range(10):
        try:
            return db_pool.getconn()
        except psycopg2.pool.PoolError:
            if attempt == 9:
                raise HTTPException(status_code=503, detail="DB pool exhausted")
            time.sleep(0.1)


def _db_release(conn):
    db_pool.putconn(conn)


def _record_cache_hit():
    try:
        redis_client.incr("cache:hits")
    except Exception:
        pass


def _record_cache_miss():
    try:
        redis_client.incr("cache:misses")
    except Exception:
        pass


# ── Endpoints ──────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {
        "status": "ok",
        "instance_id": _get_instance_id(),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/products")
def list_products(response: Response):
    cache_key = "products:all"

    cached = redis_client.get(cache_key)
    if cached:
        _record_cache_hit()
        response.headers["X-Cache"] = "HIT"
        return JSONResponse(content=json.loads(cached))

    _record_cache_miss()
    conn = _db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, price, category, created_at::text FROM products LIMIT 100"
            )
            rows = cur.fetchall()
        products = [
            {"id": r[0], "name": r[1], "price": float(r[2]), "category": r[3], "created_at": r[4]}
            for r in rows
        ]
    finally:
        _db_release(conn)

    redis_client.setex(cache_key, PRODUCT_CACHE_TTL, json.dumps(products))
    response.headers["X-Cache"] = "MISS"
    return products


@app.get("/api/products/{product_id}")
def get_product(product_id: int, response: Response):
    cache_key = f"products:{product_id}"

    cached = redis_client.get(cache_key)
    if cached:
        _record_cache_hit()
        response.headers["X-Cache"] = "HIT"
        return JSONResponse(content=json.loads(cached))

    _record_cache_miss()
    conn = _db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, price, category, created_at::text FROM products WHERE id = %s",
                (product_id,),
            )
            row = cur.fetchone()
    finally:
        _db_release(conn)

    if not row:
        raise HTTPException(status_code=404, detail="Product not found")

    product = {"id": row[0], "name": row[1], "price": float(row[2]), "category": row[3], "created_at": row[4]}
    redis_client.setex(cache_key, PRODUCT_CACHE_TTL, json.dumps(product))
    response.headers["X-Cache"] = "MISS"
    return product


@app.get("/api/inventory/{product_id}")
def get_inventory(product_id: int):
    cache_key = f"inventory:{product_id}"
    cached = redis_client.get(cache_key)
    if cached:
        return JSONResponse(content=json.loads(cached))

    conn = _db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT product_id, quantity, updated_at::text FROM inventory WHERE product_id = %s",
                (product_id,),
            )
            row = cur.fetchone()
    finally:
        _db_release(conn)

    if not row:
        raise HTTPException(status_code=404, detail="Inventory record not found")

    result = {"product_id": row[0], "quantity": row[1], "updated_at": row[2]}
    # 10-second TTL keeps RDS load manageable under peak traffic while staying near-real-time
    redis_client.setex(cache_key, 10, json.dumps(result))
    return result


class CheckoutRequest(BaseModel):
    session_token: str
    product_id: int
    quantity: int


@app.post("/api/checkout", status_code=201)
def checkout(payload: CheckoutRequest):
    conn = _db_conn()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            # Validate session
            cur.execute(
                "SELECT user_id FROM sessions WHERE token = %s AND expires_at > NOW()",
                (payload.session_token,),
            )
            session = cur.fetchone()
            if not session:
                raise HTTPException(status_code=401, detail="Invalid or expired session")

            user_id = session[0]

            # Lock inventory row for atomic decrement
            cur.execute(
                "SELECT quantity FROM inventory WHERE product_id = %s FOR UPDATE",
                (payload.product_id,),
            )
            inv = cur.fetchone()
            if not inv:
                raise HTTPException(status_code=404, detail="Product not in inventory")

            if inv[0] < payload.quantity:
                raise HTTPException(status_code=409, detail="Insufficient stock")

            cur.execute(
                "UPDATE inventory SET quantity = quantity - %s, updated_at = NOW() WHERE product_id = %s",
                (payload.quantity, payload.product_id),
            )

            cur.execute(
                """INSERT INTO orders (session_token, user_id, product_id, quantity)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (payload.session_token, user_id, payload.product_id, payload.quantity),
            )
            order_id = cur.fetchone()[0]

        conn.commit()
        return {"order_id": order_id, "status": "confirmed"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="Checkout failed") from exc
    finally:
        conn.autocommit = True
        _db_release(conn)


@app.get("/api/metrics")
def metrics():
    hits = redis_client.get("cache:hits") or "0"
    misses = redis_client.get("cache:misses") or "0"

    hits_int = int(hits)
    misses_int = int(misses)
    total = hits_int + misses_int
    cache_hit_rate = round(hits_int / total, 4) if total > 0 else 0.0

    conn = _db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
            active_connections = cur.fetchone()[0]
    finally:
        _db_release(conn)

    return {
        "cache_hits": hits_int,
        "cache_misses": misses_int,
        "cache_hit_rate": cache_hit_rate,
        "active_db_connections": active_connections,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
