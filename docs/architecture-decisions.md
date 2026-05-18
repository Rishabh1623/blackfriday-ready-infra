# Architecture Decision Records

---

## ADR-001: Warm Pool + Scheduled Scaling

**Status:** Accepted

### Context

Auto Scaling Groups launch new EC2 instances on demand when traffic increases. On Amazon Linux 2023, installing Python dependencies and starting the uvicorn service takes 2–4 minutes. During a Black Friday spike (where traffic can increase 10x in under 60 seconds), instances that are still initialising are not available to serve traffic. Target tracking reacts to load that is already happening — by the time the ASG decides to scale, the spike is already causing degraded latency.

The two compounding problems are:
1. **Cold-start lag:** new instances take too long to become healthy before peak traffic hits
2. **Reactive-only scaling:** target tracking policies respond to observed load, not anticipated load

### Decision

Implement a two-layer pre-scaling strategy:

1. **Warm Pool (min_size=3, pool_state=Stopped, reuse_on_scale_in=true):** Three EC2 instances are fully initialised (user_data has run, app is installed) and held in `Stopped` state. When the ASG needs to scale out, it starts these warm instances instead of launching new ones. Starting a stopped instance takes ~30 seconds vs ~3 minutes for a cold launch.

2. **Scheduled Scaling (desired=10 at 19:45 UTC):** A cron-based scheduled action increases `desired_capacity` from 2 to 10 at 19:45 UTC — 15 minutes before the expected 20:00 UTC peak. The warm pool fills the gap, so those 8 additional instances are ready well before traffic arrives. A second scheduled action at 23:00 UTC returns `desired_capacity` to 2.

### Consequences

**Positive:**
- Near-zero cold-start impact during planned peaks
- Warm instances absorb the first wave of traffic while target tracking scales further
- `reuse_on_scale_in=true` means instances returning to the pool keep their warm state, reducing future cold starts

**Negative:**
- ~3 stopped EC2 instances run at all times, incurring ~$20–30/month in EBS and partial EC2 costs
- Requires ops team to update the cron schedule if peak time changes
- The warm pool count (3) is a manual estimate — if a spike exceeds it, cold instances fill the remainder

### Alternatives Considered

- **Predictive Scaling:** AWS can forecast based on CloudWatch history. Rejected because this is a new deployment with no historical data; predictive scaling needs at least 24 hours of metrics.
- **Lambda + ECS Fargate:** Would eliminate cold-start entirely. Rejected per scope — this project demonstrates EC2-based auto-scaling patterns.
- **Pre-baked AMI:** Bake the app into a custom AMI to reduce initialisation time. Valid but adds a CI/CD dependency. Could complement this approach in production.

---

## ADR-002: RDS Proxy for Connection Pooling

**Status:** Accepted

### Context

PostgreSQL has a maximum connection limit determined by `max_connections`, which defaults to around 85 for `db.t3.medium` (based on available RAM: `LEAST({DBInstanceClassMemory/9531392}, 5000)`). Each uvicorn worker holds a psycopg2 `ThreadedConnectionPool` with up to 20 connections. At peak scale (20 ASG instances × 4 workers × 20 pool connections), the theoretical maximum is 1,600 concurrent connections — 18x the database limit. This causes `FATAL: remaining connection slots are reserved` errors and cascading failures.

### Decision

Place an **RDS Proxy** between the application and the database:

- The proxy maintains a small persistent connection pool to RDS
- Application instances connect to the proxy endpoint instead of the database endpoint directly
- `max_connections_percent = 100` allows the proxy to use all available database connections
- `borrow_timeout = 120` seconds — if all pooled connections are in use, applications wait up to 2 minutes before failing
- `require_tls = true` — encrypts the proxy→database link
- The proxy authenticates to Secrets Manager via an IAM role, then uses those credentials to connect to RDS

### Consequences

**Positive:**
- Multiplexes potentially thousands of application connections onto tens of database connections
- Automatic failover: the proxy reconnects to a new RDS primary within seconds after a failover, without application-side reconnection logic
- Credentials rotation in Secrets Manager is seamless — the proxy picks up the new password without restarts

**Negative:**
- RDS Proxy costs approximately $0.015 per vCPU-hour of the proxied database instance (~$11/month for db.t3.medium)
- Adds ~1ms of latency per query due to the extra network hop
- RDS Proxy does not support all PostgreSQL features (e.g., `SET` commands that persist across transactions behave differently with multiplexing)

### Alternatives Considered

- **PgBouncer on EC2:** Open-source connection pooler, more configurable. Rejected because it requires managing an additional EC2 instance, including HA, monitoring, and patching.
- **Increase `max_connections` via parameter group:** Can be raised, but the underlying RAM constraint means very high values lead to OOM. Not a scalable solution.
- **Application-level pooling only:** psycopg2's ThreadedConnectionPool already pools within one process, but does nothing to coordinate across processes and instances.

---

## ADR-003: Layered Caching (CloudFront + Redis)

**Status:** Accepted

### Context

During peak traffic, the product catalog API (`GET /api/products` and `GET /api/products/{id}`) accounts for approximately 60% of all requests. These endpoints query a PostgreSQL table that changes infrequently — products are added or updated by ops teams, not by customers. Serving these from the database on every request wastes compute and database connections, and adds unnecessary latency.

Inventory and checkout endpoints have the opposite requirement: they must always reflect real-time state.

### Decision

Implement a two-layer cache hierarchy:

**Layer 1 — CloudFront (edge cache):**
- `GET /api/products*` responses are cached at CloudFront edge nodes for 300 seconds
- Requests that hit the cache never reach the origin (ALB/EC2/RDS)
- `GET /api/inventory*` and `GET /api/checkout*` have TTL=0, bypassing CloudFront entirely
- At peak, a warm CloudFront cache can absorb the majority of product catalog traffic with sub-10ms response times from the nearest PoP

**Layer 2 — Redis (application cache, cache-aside pattern):**
- On a CloudFront cache miss (or direct ALB hit), the FastAPI app checks Redis before querying RDS
- Cache key: `products:all` for the list, `products:{id}` for individual products
- TTL: 300 seconds (matching CloudFront TTL to keep both layers coherent)
- `X-Cache: HIT` / `X-Cache: MISS` header returned so CloudFront cacheability is observable
- Redis hit/miss counters are tracked in `cache:hits` / `cache:misses` keys and exposed at `/api/metrics`

**TTL Strategy by Endpoint:**

| Endpoint | CloudFront TTL | Redis TTL | Rationale |
|---|---|---|---|
| `GET /api/products*` | 300s | 300s | Catalog rarely changes; staleness is acceptable |
| `GET /api/inventory*` | 0 (no cache) | None | Real-time stock must be accurate |
| `POST /api/checkout` | 0 (no cache) | None | Stateful mutation, never cacheable |

### Consequences

**Positive:**
- Under full cache-warm conditions, product catalog requests never hit the origin
- Significantly reduces RDS connection pressure during peak
- Redis reader endpoint can be used for reads, offloading the primary

**Negative:**
- Product data can be up to 5 minutes stale at CloudFront edges (and up to 5 minutes stale in Redis)
- Cache invalidation on product updates requires either waiting for TTL expiry or explicit cache purges (not implemented here)
- Two caches increase operational complexity: both must be monitored for hit rate

### Alternatives Considered

- **Cache only at Redis (no CloudFront caching):** Simpler, but does not absorb traffic at the edge. All requests still reach EC2 instances.
- **DAX (DynamoDB Accelerator):** Only applicable if the database were DynamoDB. Not relevant to this RDS-based design.
- **Longer TTLs:** Would improve cache effectiveness but increase staleness risk for prices/availability.

---

## ADR-004: WAF Rate Limiting

**Status:** Accepted

### Context

Black Friday is a well-known target for bot attacks, credential stuffing, and inventory-hoarding bots that programmatically drain stock of high-demand items (sneaker bots, GPU scalpers, etc.). Without rate limiting, a single malicious actor or misconfigured bot can:
1. Exhaust the connection pool and degrade service for legitimate users
2. Scrape the entire product catalog repeatedly, bypassing CloudFront caching
3. Attempt SQL injection on checkout endpoints

### Decision

Deploy **AWS WAFv2** (REGIONAL scope, associated with the ALB) with three rules:

1. **IP-based rate limit (priority 1, block action):** Block any source IP that sends more than 2,000 requests in any 5-minute window. This is approximately 6.7 requests/second — well above normal browsing behaviour but below legitimate high-frequency API consumers. Action is `block` (HTTP 403), not `count`.

2. **AWSManagedRulesCommonRuleSet (priority 2):** AWS-maintained ruleset covering OWASP Top 10 patterns including path traversal, log4j, and known bad bots. Uses `override_action = none` (enforces blocks, not just counts).

3. **AWSManagedRulesSQLiRuleSet (priority 3):** Detects SQL injection patterns in query strings, headers, and request bodies. Protects the `POST /api/checkout` endpoint from injection attempts targeting the inventory `FOR UPDATE` query.

The WAF is also passed as `web_acl_id` to the CloudFront distribution, providing edge-level enforcement before requests reach the ALB.

### Consequences

**Positive:**
- Legitimate Black Friday traffic (human shoppers, mobile apps) stays well below the 2,000/5-min threshold
- Managed rulesets receive automatic updates from AWS without manual rule maintenance
- WAF metrics (`BlockedRequests`) appear on the CloudWatch dashboard for real-time visibility

**Negative:**
- Managed rules can produce false positives — legitimate requests matching rule patterns will be blocked. `override_action = count` should be used first in a staging environment before switching to block.
- WAF costs: ~$10/rule/month + $1 per million requests evaluated. For high-traffic scenarios this adds up.
- Rate limit of 2,000/5-min may be too low for legitimate API integrations (e.g., a partner system doing bulk price checks). Separate rules with higher limits could be added for trusted IP ranges.

### Alternatives Considered

- **CloudFront-only rate limiting:** CloudFront does not natively support IP-based rate limiting without WAF.
- **Application-level rate limiting (e.g., slowapi):** Requires every EC2 instance to track request counts, which is unreliable across a fleet without a shared store. WAF operates centrally before traffic reaches instances.
- **AWS Shield Advanced:** Provides DDoS protection at network and transport layers. Useful for volumetric attacks but significantly more expensive (~$3,000/month). Not warranted for this architecture.
