# BlackFriday-Ready Infrastructure

A production-grade AWS scalability reference architecture that demonstrates how to handle peak traffic events — Black Friday, end-of-month sales spikes, flash sales — without downtime or degraded latency.

---

## Architecture Overview

```
                          ┌─────────────────────────────────────────┐
                          │            Internet (Users)             │
                          └───────────────────┬─────────────────────┘
                                              │
                          ┌───────────────────▼─────────────────────┐
                          │         CloudFront (PriceClass_100)     │
                          │  /api/products* TTL=300s                │
                          │  /api/inventory* TTL=0 (bypass)         │
                          │  /api/checkout*  TTL=0 (bypass)         │
                          └───────────────────┬─────────────────────┘
                                              │
                          ┌───────────────────▼─────────────────────┐
                          │     WAF WebACL (REGIONAL)               │
                          │  • Rate limit: 2000 req/5min/IP → block │
                          │  • AWSManagedRulesCommonRuleSet          │
                          │  • AWSManagedRulesSQLiRuleSet            │
                          └───────────────────┬─────────────────────┘
                                              │
                          ┌───────────────────▼─────────────────────┐
                          │   ALB (3 public subnets, us-east-1)     │
                          │   Target Group: port 8000, /health      │
                          └──────────┬────────────────┬─────────────┘
                                     │                │
                    ┌────────────────▼──┐        ┌───▼────────────────┐
                    │  EC2 t3.medium    │  ...   │  EC2 t3.medium     │
                    │  FastAPI / uvicorn│        │  FastAPI / uvicorn  │
                    │  (private subnet) │        │  (private subnet)  │
                    └────────┬──────────┘        └───────┬────────────┘
                             │   ASG: min=2, max=20      │
                             │   Warm pool: 3 stopped    │
                             │   Scale-out: 19:45 UTC    │
                             └──────────┬────────────────┘
                                        │
                  ┌─────────────────────┼──────────────────────┐
                  │                     │                      │
     ┌────────────▼──────────┐  ┌───────▼────────┐  ┌────────▼────────────┐
     │  RDS Proxy            │  │  ElastiCache   │  │  Secrets Manager    │
     │  borrow_timeout=120s  │  │  Redis 7.0     │  │  DB credentials     │
     │  max_conn_pct=100     │  │  1P + 1R       │  │  (never hardcoded)  │
     └──────────┬────────────┘  │  TLS + encrypt │  └─────────────────────┘
                │               └────────────────┘
     ┌──────────▼────────────┐
     │  RDS PostgreSQL 15    │
     │  db.t3.medium         │
     │  Encrypted, 7d backup │
     └───────────────────────┘
```

---

## Architecture Decisions

### 1. Warm Pool + Scheduled Scaling

**Problem:** New EC2 instances take 2–4 minutes to initialise (install dependencies, start service). Target tracking reacts *after* load spikes, so cold instances can't absorb the first wave.

**Solution:** A warm pool holds 3 pre-initialised stopped instances. A scheduled action pre-scales to 10 instances at 19:45 UTC — 15 minutes before peak. Warm instances start in ~30 seconds.

**Tradeoff:** ~$20–30/month for warm pool instances; cron schedule must be updated if peak time shifts.

### 2. RDS Proxy

**Problem:** At full ASG scale (20 instances × 4 workers × 20 pool connections = 1,600 potential connections), PostgreSQL's ~85 connection limit on `db.t3.medium` would be exhausted, causing `FATAL: too many connections` errors.

**Solution:** RDS Proxy multiplexes thousands of application connections onto the database's actual connection limit. `borrow_timeout=120s` queues requests rather than failing immediately.

**Tradeoff:** ~$11/month additional cost; adds ~1ms latency per query.

### 3. Layered Caching (CloudFront + Redis)

**Problem:** Product catalog reads account for 60% of traffic but the data changes infrequently. Serving every request from RDS wastes connections and adds latency.

**Solution:** Two-layer cache — CloudFront caches `/api/products*` responses at the edge for 300s; Redis caches the same data in-process for 300s. Inventory and checkout always bypass both layers.

**Tradeoff:** Product data can be up to 5 minutes stale; cache invalidation on product updates requires explicit purge logic.

### 4. WAF Rate Limiting

**Problem:** Black Friday attracts inventory bots, scraper bots, and credential stuffing. Uncontrolled bot traffic can exhaust EC2 connections and degrade the experience for legitimate shoppers.

**Solution:** WAF blocks IPs exceeding 2,000 requests per 5 minutes. AWS managed rulesets cover OWASP Top 10 and SQL injection. Rules apply at both CloudFront (edge) and ALB.

**Tradeoff:** Managed rules can produce false positives; ~$10/rule/month + $1/million requests.

---

## Prerequisites

| Tool | Minimum Version |
|---|---|
| Terraform | 1.6+ |
| AWS CLI | 2.x (configured with appropriate permissions) |
| Python | 3.11+ |
| k6 | 0.50+ |
| psycopg2 dependencies | `libpq-dev` on Ubuntu, `postgresql-libs` on AL2 |

---

## Deploy Instructions

### Step 1: Bootstrap Terraform Backend

Create the S3 bucket and DynamoDB table for remote state. Replace `<ACCOUNT_ID>` with your AWS account ID:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
BUCKET="blackfriday-tfstate-${ACCOUNT_ID}"

aws s3api create-bucket \
  --bucket "$BUCKET" \
  --region "$REGION"

aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws dynamodb create-table \
  --table-name blackfriday-tfstate-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region "$REGION"
```

Update `terraform/backend.tf` — replace `blackfriday-tfstate-REPLACE_WITH_ACCOUNT_ID` with `blackfriday-tfstate-${ACCOUNT_ID}`.

### Step 2: Deploy Infrastructure

```bash
cd terraform/
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

Deployment takes approximately 15–20 minutes (RDS and RDS Proxy are the slowest resources).

### Step 3: Capture Outputs

```bash
ALB_DNS=$(terraform output -raw alb_dns_name)
CF_DOMAIN=$(terraform output -raw cloudfront_domain_name)
RDS_PROXY=$(terraform output -raw rds_proxy_endpoint)
CACHE_HOST=$(terraform output -raw elasticache_primary_endpoint)
SECRET_ARN=$(terraform output -raw db_secret_arn)
```

### Step 4: Seed the Database

```bash
# Retrieve credentials from Secrets Manager
SECRET=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRET_ARN" --query SecretString --output text)

export DB_HOST="$RDS_PROXY"
export DB_NAME="blackfriday"
export DB_USER=$(echo "$SECRET" | python3 -c "import sys,json; print(json.load(sys.stdin)['username'])")
export DB_PASSWORD=$(echo "$SECRET" | python3 -c "import sys,json; print(json.load(sys.stdin)['password'])")

cd ../app/
pip3 install -r requirements.txt
python3 seed.py
```

### Step 5: Verify the API

```bash
# Health check — should return instance ID and timestamp
curl http://$ALB_DNS/health

# Product list — first call is a MISS, second is a HIT
curl -I http://$ALB_DNS/api/products
curl -I http://$ALB_DNS/api/products   # X-Cache: HIT

# Inventory (always live)
curl http://$ALB_DNS/api/inventory/1
```

### Step 6: Run Load Test

```bash
cd ../load-test/
k6 run --env BASE_URL="http://$CF_DOMAIN" k6-script.js
# Results written to load-test/results/summary.json
```

### Step 7: Import CloudWatch Dashboard

Replace the placeholder values in `monitoring/cloudwatch-dashboard.json`:

| Placeholder | Replace with |
|---|---|
| `${ALB_ARN_SUFFIX}` | `terraform output -raw` for `alb_arn_suffix` |
| `${ASG_NAME}` | ASG name from `terraform output` or AWS Console |
| `${DB_INSTANCE_ID}` | `blackfriday-prod-postgres` |
| `${ELASTICACHE_ID}` | `blackfriday-prod-redis` |
| `${WAF_ACL_NAME}` | `blackfriday-prod-web-acl` |
| `${AWS_REGION}` | `us-east-1` |

```bash
aws cloudwatch put-dashboard \
  --dashboard-name BlackFriday-Ops \
  --dashboard-body file://monitoring/cloudwatch-dashboard.json
```

---

## Cost Estimate (Monthly, us-east-1)

| Resource | Config | Est. Cost |
|---|---|---|
| EC2 ASG (baseline) | 2× t3.medium | ~$60 |
| EC2 Warm Pool | 3× t3.medium (stopped, EBS only) | ~$9 |
| EC2 ASG (peak 3h/day) | +8× t3.medium | ~$30 |
| ALB | 1× ALB | ~$16 |
| NAT Gateway | 1× NAT + data transfer | ~$32 |
| RDS PostgreSQL | db.t3.medium + 20GB gp3 | ~$50 |
| RDS Proxy | db.t3.medium (2 vCPU) | ~$22 |
| ElastiCache Redis | 2× cache.t3.micro | ~$25 |
| CloudFront | PriceClass_100, 10M req/mo | ~$10 |
| WAF | 3 rules + 10M req/mo | ~$41 |
| Secrets Manager | 1 secret | ~$0.40 |
| CloudWatch | Dashboard + logs | ~$5 |
| **Total** | | **~$300/month** |

Costs are estimates. Actual costs depend on traffic volume, data transfer, and storage growth.

---

## Key Metrics to Watch During Peak

| Metric | Warning | Critical | Dashboard Widget |
|---|---|---|---|
| ALB p99 latency | > 500ms | > 2000ms | ALB Latency |
| ASG in-service instances | — | = max (20) | ASG Instances |
| RDS connections | > 60 | > 80 | RDS Connections |
| Cache hit rate | < 80% | < 50% | Cache Hit Rate |
| WAF blocked requests | > 1000/min | > 10000/min | WAF Blocked |
| ALB 5XX errors | > 10/min | > 100/min | ALB 5XX Count |
| RDS freeable memory | < 200MB | < 100MB | RDS Memory |

---

## Teardown

```bash
cd terraform/
# Remove deletion protection from RDS first
aws rds modify-db-instance \
  --db-instance-identifier blackfriday-prod-postgres \
  --no-deletion-protection \
  --apply-immediately

terraform destroy
```

> Note: The S3 state bucket and DynamoDB lock table are not managed by Terraform and must be deleted manually.
