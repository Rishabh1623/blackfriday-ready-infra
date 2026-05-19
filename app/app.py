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
from fastapi.responses import HTMLResponse, JSONResponse
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


APP_VERSION = "1.3.0"

_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>PeakMart — Peak Season Deals</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d0d0d; color: #f0f0f0; font-family: 'Segoe UI', sans-serif; min-height: 100vh; }

  header {
    background: linear-gradient(135deg, #1a1a1a 0%, #2a1500 100%);
    border-bottom: 2px solid #ff6a00;
    padding: 18px 32px;
    display: flex; align-items: center; justify-content: space-between;
  }
  header h1 { font-size: 1.6rem; font-weight: 800; letter-spacing: 1px; }
  header h1 span { color: #ff6a00; }
  .badge {
    display: inline-flex; align-items: center; gap: 6px;
    background: #1a1a1a; border: 1px solid #333; border-radius: 999px;
    padding: 6px 14px; font-size: 0.8rem;
  }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; }
  .dot.error { background: #ef4444; }

  .metrics-bar {
    background: #141414; border-bottom: 1px solid #222;
    display: flex; gap: 32px; padding: 12px 32px; font-size: 0.82rem; color: #aaa;
  }
  .metrics-bar span b { color: #ff6a00; }

  .toolbar {
    padding: 20px 32px 0; display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  }
  .toolbar input {
    background: #1c1c1c; border: 1px solid #333; border-radius: 8px;
    color: #f0f0f0; padding: 8px 14px; font-size: 0.9rem; width: 240px;
    outline: none;
  }
  .toolbar input:focus { border-color: #ff6a00; }
  .filter-btn {
    background: #1c1c1c; border: 1px solid #333; border-radius: 8px;
    color: #aaa; padding: 8px 14px; font-size: 0.82rem; cursor: pointer;
    transition: all .15s;
  }
  .filter-btn.active, .filter-btn:hover { background: #ff6a00; border-color: #ff6a00; color: #fff; }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 18px; padding: 20px 32px 40px;
  }

  .card {
    background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px;
    padding: 18px; display: flex; flex-direction: column; gap: 10px;
    transition: border-color .2s, transform .2s;
  }
  .card:hover { border-color: #ff6a00; transform: translateY(-2px); }
  .card-category {
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px;
    color: #ff6a00; font-weight: 700;
  }
  .card-name { font-size: 0.95rem; font-weight: 600; line-height: 1.3; flex: 1; }
  .card-price { font-size: 1.4rem; font-weight: 800; color: #ff6a00; }
  .card-inv {
    font-size: 0.78rem; color: #888; display: flex; align-items: center; gap: 6px;
  }
  .inv-dot { width: 6px; height: 6px; border-radius: 50%; background: #22c55e; flex-shrink: 0; }
  .inv-dot.low { background: #f59e0b; }
  .inv-dot.out { background: #ef4444; }

  .skeleton {
    background: linear-gradient(90deg, #1f1f1f 25%, #2a2a2a 50%, #1f1f1f 75%);
    background-size: 200% 100%;
    animation: shimmer 1.2s infinite;
    border-radius: 8px;
  }
  @keyframes shimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }

  #error-msg {
    display: none; margin: 40px auto; max-width: 400px; text-align: center; color: #ef4444;
  }
</style>
</head>
<body>

<header>
  <h1>PEAK<span>MART</span></h1>
  <p style="font-size:0.72rem;color:#888;letter-spacing:2px;text-transform:uppercase;margin-top:2px">Peak Season Deals</p>
  <div class="badge">
    <span class="dot" id="health-dot"></span>
    <span id="health-text">Checking...</span>
  </div>
</header>

<div class="metrics-bar" id="metrics-bar">
  <span>Cache hits: <b id="m-hits">—</b></span>
  <span>Cache misses: <b id="m-misses">—</b></span>
  <span>Hit rate: <b id="m-rate">—</b></span>
  <span>Active DB connections: <b id="m-conn">—</b></span>
</div>

<div class="toolbar">
  <input id="search" type="text" placeholder="Search products..."/>
  <div id="filters"></div>
</div>

<div class="grid" id="grid">
  <!-- skeleton cards -->
  ${Array.from({length: 12}).map(() => `
  <div class="card">
    <div class="skeleton" style="height:12px;width:60%"></div>
    <div class="skeleton" style="height:16px;width:90%;margin-top:4px"></div>
    <div class="skeleton" style="height:28px;width:40%;margin-top:4px"></div>
    <div class="skeleton" style="height:10px;width:50%;margin-top:4px"></div>
  </div>`).join('')}
</div>
<div id="error-msg">Failed to load products. Please try again.</div>

<script>
let allProducts = [];
let inventoryCache = {};
let activeCategory = 'All';

async function fetchHealth() {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    document.getElementById('health-dot').className = 'dot';
    document.getElementById('health-text').textContent = 'Live · v' + d.version;
  } catch {
    document.getElementById('health-dot').className = 'dot error';
    document.getElementById('health-text').textContent = 'Offline';
  }
}

async function fetchMetrics() {
  try {
    const r = await fetch('/api/metrics');
    const d = await r.json();
    document.getElementById('m-hits').textContent = d.cache_hits.toLocaleString();
    document.getElementById('m-misses').textContent = d.cache_misses.toLocaleString();
    document.getElementById('m-rate').textContent = (d.cache_hit_rate * 100).toFixed(1) + '%';
    document.getElementById('m-conn').textContent = d.active_db_connections;
  } catch {}
}

async function fetchInventory(id) {
  if (inventoryCache[id] !== undefined) return inventoryCache[id];
  try {
    const r = await fetch('/api/inventory/' + id);
    if (!r.ok) { inventoryCache[id] = null; return null; }
    const d = await r.json();
    inventoryCache[id] = d.quantity;
    return d.quantity;
  } catch { inventoryCache[id] = null; return null; }
}

function invLabel(qty) {
  if (qty === null) return { cls: '', text: 'Stock unknown' };
  if (qty === 0)   return { cls: 'out', text: 'Out of stock' };
  if (qty <= 20)   return { cls: 'low', text: qty + ' left — low stock' };
  return { cls: '', text: qty + ' in stock' };
}

function renderCards(products) {
  const grid = document.getElementById('grid');
  grid.innerHTML = products.map(p => {
    const inv = inventoryCache[p.id];
    const { cls, text } = invLabel(inv !== undefined ? inv : null);
    return `<div class="card" data-category="${p.category}">
      <div class="card-category">${p.category}</div>
      <div class="card-name">${p.name}</div>
      <div class="card-price">$${p.price.toFixed(2)}</div>
      <div class="card-inv">
        <span class="inv-dot ${cls}"></span>
        <span id="inv-${p.id}">${inv !== undefined ? text : 'Loading...'}</span>
      </div>
    </div>`;
  }).join('');
}

function filteredProducts() {
  const q = document.getElementById('search').value.toLowerCase();
  return allProducts.filter(p =>
    (activeCategory === 'All' || p.category === activeCategory) &&
    p.name.toLowerCase().includes(q)
  );
}

function applyFilters() { renderCards(filteredProducts()); }

function buildFilters(products) {
  const cats = ['All', ...new Set(products.map(p => p.category))];
  const wrap = document.getElementById('filters');
  wrap.innerHTML = cats.map(c =>
    `<button class="filter-btn${c === 'All' ? ' active' : ''}" data-cat="${c}">${c}</button>`
  ).join('');
  wrap.addEventListener('click', e => {
    const btn = e.target.closest('.filter-btn');
    if (!btn) return;
    activeCategory = btn.dataset.cat;
    wrap.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyFilters();
  });
}

async function loadInventoryBatch(products) {
  await Promise.all(products.map(async p => {
    await fetchInventory(p.id);
    const el = document.getElementById('inv-' + p.id);
    if (el) {
      const { cls, text } = invLabel(inventoryCache[p.id]);
      el.textContent = text;
      const dot = el.previousElementSibling;
      if (dot) dot.className = 'inv-dot ' + cls;
    }
  }));
}

async function init() {
  fetchHealth();
  fetchMetrics();

  try {
    const r = await fetch('/api/products');
    if (!r.ok) throw new Error();
    allProducts = await r.json();

    buildFilters(allProducts);
    renderCards(allProducts);
    await loadInventoryBatch(allProducts);
    renderCards(filteredProducts());
  } catch {
    document.getElementById('grid').innerHTML = '';
    document.getElementById('error-msg').style.display = 'block';
  }

  document.getElementById('search').addEventListener('input', applyFilters);
  setInterval(fetchMetrics, 10000);
  setInterval(fetchHealth, 30000);
}

init();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(content=_UI_HTML)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
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
