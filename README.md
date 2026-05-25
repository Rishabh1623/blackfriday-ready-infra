# BlackFriday-Ready Infrastructure

A production-grade AWS scalability reference architecture that demonstrates how to handle peak traffic events — Black Friday, end-of-month sales spikes, flash sales — without downtime or degraded latency.

---

## Repository Structure

```
blackfriday-ready-infra/
├── .github/
│   └── workflows/
│       └── deploy.yml          # CI/CD: lint → plan → deploy → instance refresh
│
├── terraform/                  # All infrastructure as code
│   ├── main.tf                 # Root module — wires all modules together
│   ├── variables.tf            # Input variables (region, env, instance types, domain)
│   ├── outputs.tf              # Exported values (ALB DNS, CloudFront domain, role ARN, etc.)
│   ├── backend.tf              # S3 + DynamoDB remote state config
│   └── modules/
│       ├── networking/         # VPC, subnets (public/private), IGW, NAT, route tables, SGs
│       ├── compute/            # ALB, HTTPS listener, ASG, warm pool, scheduled scaling
│       │   └── user_data.sh.tpl  # EC2 bootstrap: installs Python, pulls app from S3
│       ├── acm/                # ACM certificate + DNS validation (Route53 or manual)
│       ├── rds/                # PostgreSQL 15, RDS Proxy, Secrets Manager integration
│       ├── elasticache/        # Redis 7.0 replication group (1 primary + 1 replica)
│       ├── cloudfront/         # CloudFront distribution + cache behaviours per path
│       ├── waf/                # WAFv2 WebACL: rate limit + managed rule sets
│       └── monitoring/         # CloudWatch alarms (10) + SNS email topic
│
├── app/
│   ├── app.py                  # FastAPI app: /health, /api/products, /api/inventory, /api/checkout
│   ├── requirements.txt        # Python dependencies (fastapi, uvicorn, psycopg2, redis)
│   └── seed.py                 # Populates RDS with 100 sample products
│
├── load-test/
│   ├── k6-script.js            # k6 load test: 3 phases (baseline → ramp → 500 VU peak)
│   └── results/
│       └── summary.json        # Actual test results from last run
│
├── monitoring/
│   └── cloudwatch-dashboard.json  # CloudWatch dashboard definition (import via CLI)
│
└── docs/
    └── architecture-decisions.md  # Detailed ADRs for all key design choices
```

---

## Architecture Overview

```
                        ┌─────────────────────────────────────────┐
                        │            Internet (Users)             │
                        └───────────────────┬─────────────────────┘
                                            │  HTTPS (TLS 1.2+)
                        ┌───────────────────▼─────────────────────┐
                        │   CloudFront (PriceClass_100)           │
                        │   redirect-to-https (all behaviors)     │
                        │   /api/products* TTL=300s               │
                        │   /api/inventory* TTL=0 (bypass)        │
                        │   /api/checkout*  TTL=0 (bypass)        │
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
                        │   :80 → 301 redirect to HTTPS           │
                        │   :443 → forward (ACM cert, TLS 1.3)    │
                        └──────────┬────────────────┬─────────────┘
                                   │                │
                  ┌────────────────▼──┐        ┌───▼────────────────┐
                  │  EC2 t3.medium    │  ...   │  EC2 t3.medium     │
                  │  FastAPI/uvicorn  │        │  FastAPI/uvicorn    │
                  │  (private subnet) │        │  (private subnet)  │
                  └────────┬──────────┘        └───────┬────────────┘
                           │   ASG: min=2, max=20      │
                           │   Warm pool: 3 stopped    │
                           │   Pre-baked AMI (~30s boot)│
                           │   Scale-out: 19:45 UTC    │
                           └──────────┬────────────────┘
                                      │
                ┌─────────────────────┼──────────────────────┐
                │                     │                      │
   ┌────────────▼──────────┐  ┌───────▼────────┐  ┌────────▼────────────┐
   │  RDS Proxy            │  │  ElastiCache   │  │  Secrets Manager    │
   │  borrow_timeout=120s  │  │  Redis 7.0     │  │  DB credentials     │
   │  max_conn_pct=100     │  │  1P + 1R       │  │  (never hardcoded)  │
   └──────────┬────────────┘  └────────────────┘  └─────────────────────┘
              │
   ┌──────────▼────────────┐       ┌─────────────────────────────────────┐
   │  RDS PostgreSQL 15    │       │  CloudWatch Alarms (10) → SNS       │
   │  db.t3.medium         │       │  ALB: 5xx, latency, unhealthy hosts │
   │  Encrypted, 7d backup │       │  ASG: CPU                           │
   └───────────────────────┘       │  RDS: CPU, connections, storage     │
                                   │  ElastiCache: CPU, hit rate         │
                                   └─────────────────────────────────────┘
```
 ![Architecture Diagram](https://github.com/Rishabh1623/blackfriday-ready-infra/blob/main/docs/Solution%20Architect%20Diagram.jpg)



## Architecture Decisions

### 1. Warm Pool + Scheduled Scaling

**Problem:** New EC2 instances take 2–4 minutes to initialise (install dependencies, start service). Target tracking reacts *after* load spikes, so cold instances can't absorb the first wave.

**Solution:** A warm pool holds 3 pre-initialised stopped instances. A scheduled action pre-scales to 10 instances at 19:45 UTC — 15 minutes before peak. Warm instances start in ~30 seconds. A pre-baked AMI (`ami-0efefd093d7345801`) skips `pip install` at boot, cutting cold-start further.

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

### 5. HTTPS — ACM + ALB + CloudFront

**Problem:** HTTP-only traffic is unacceptable for an e-commerce checkout flow (credentials, card data in transit).

**Solution:** ACM certificate with DNS validation. ALB port 443 listener with `ELBSecurityPolicy-TLS13-1-2-2021-06` (TLS 1.3 preferred). Port 80 issues a permanent 301 redirect to HTTPS. CloudFront enforces `redirect-to-https` on all cache behaviors. Certificate and HTTPS listener are conditional — the stack deploys cleanly with `domain_name = ""` (no cert needed for testing).

**Tradeoff:** ACM cert requires DNS ownership validation; TLS termination at ALB adds marginal CPU overhead.

### 6. CloudWatch Alarms + SNS

**Problem:** Silent failures during Black Friday peak — a cache collapse, RDS CPU spike, or unhealthy instance behind the ALB — can go unnoticed for minutes with no on-call alert.

**Solution:** 10 CloudWatch alarms covering the full stack (ALB error rates, P99 latency, ASG CPU, RDS connections and storage, ElastiCache CPU and hit rate via metric math). All alarms publish to a single SNS topic with email subscription. Cache hit rate uses a CloudWatch metric math expression (`CacheHits / (CacheHits + CacheMisses) * 100`) rather than a single metric.

**Tradeoff:** Alarm thresholds require tuning per workload; SNS email has no on-call escalation without PagerDuty/OpsGenie integration.

### 7. GitHub Actions CI/CD with OIDC

**Problem:** Storing long-lived AWS access keys in GitHub Secrets is a credential exposure risk. Static keys cannot be easily rotated and are a common source of supply-chain attacks.

**Solution:** GitHub Actions assumes an IAM role via OIDC (`sts:AssumeRoleWithWebIdentity`) — no keys stored anywhere. The trust policy is scoped to a specific repo using `StringLike` on the `sub` claim. The pipeline: lint → `terraform plan` (on PR, posted as comment) → `terraform apply` → S3 artifact upload → ASG instance refresh (on merge to main).

**Tradeoff:** OIDC setup requires an IAM OIDC provider in the account; `AdministratorAccess` is used for demo simplicity and should be scoped down in production.

---

## Prerequisites

| Tool | Minimum Version |
|---|---|
| Terraform | 1.6+ |
| AWS CLI | 2.x (configured with appropriate permissions) |
| Python | 3.11+ |
| k6 | 0.50+ |

---

## Deploy Instructions

### Step 1: Bootstrap Terraform Backend

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
BUCKET="blackfriday-tfstate-${ACCOUNT_ID}"

aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
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
ASG_NAME=$(terraform output -raw asg_name)
SNS_TOPIC=$(terraform output -raw sns_alerts_topic_arn)
GH_ROLE=$(terraform output -raw github_actions_role_arn)
```

### Step 4: Seed the Database

```bash
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
# Health check — returns instance ID, version, and timestamp
curl https://$CF_DOMAIN/health

# Product list — first call MISS, second HIT
curl -I https://$CF_DOMAIN/api/products
curl -I https://$CF_DOMAIN/api/products   # X-Cache: Hit

# Inventory (always live, bypasses cache)
curl https://$CF_DOMAIN/api/inventory/1

# HTTP redirects to HTTPS
curl -I http://$CF_DOMAIN/health          # HTTP 301
```

### Step 6: Enable HTTPS with a Custom Domain (optional)

Set your domain and Route53 hosted zone to activate end-to-end TLS:

```bash
terraform apply \
  -var="domain_name=yourdomain.com" \
  -var="route53_zone_id=Z1234567890ABC"
```

This creates an ACM certificate, adds DNS validation records to Route53, adds the HTTPS listener to the ALB, upgrades the CloudFront origin to `https-only`, and adds your domain as a CloudFront alias — all automatically.

Without a domain, the stack serves HTTPS via the default `*.cloudfront.net` certificate and HTTP on the ALB.

### Step 7: Set Up CI/CD (GitHub Actions)

1. Add a repository secret in GitHub:
   - **Name:** `AWS_DEPLOY_ROLE_ARN`
   - **Value:** `arn:aws:iam::<ACCOUNT_ID>:role/blackfriday-prod-github-actions`  
     *(or run `terraform output github_actions_role_arn`)*

2. Confirm the SNS subscription email — check your inbox for an email from `no-reply@sns.amazonaws.com` and click **Confirm subscription**.

3. Every push to `main` now runs the full pipeline automatically:
   - **Lint** → **Terraform Plan** → **Deploy** → **ASG instance refresh**
   - Pull requests get a `terraform plan` diff posted as a PR comment.

### Step 8: Run Load Test

```bash
cd ../load-test/
k6 run --env BASE_URL="https://$CF_DOMAIN" k6-script.js
```

**Verified results at 500 VUs:**

| Metric | Result | Threshold | Status |
|---|---|---|---|
| HTTP error rate | 1.84% | < 5% | ✅ Pass |
| p95 response time | 69ms | < 3,000ms | ✅ Pass |
| Product API p95 | 4ms | p99 < 2,000ms | ✅ Pass |
| Inventory API p95 | 64ms | p99 < 2,000ms | ✅ Pass |
| Checkout p95 | 129ms | p99 < 3,000ms | ✅ Pass |
| Checkout success rate | 95.4% | > 90% | ✅ Pass |
| Total requests (31 min) | 406,309 | — | — |

### Step 9: Import CloudWatch Dashboard

```bash
ALB_ARN_SUFFIX=$(terraform -chdir=terraform output -raw alb_arn_suffix 2>/dev/null || echo "")

sed \
  -e "s|\${ALB_ARN_SUFFIX}|$ALB_ARN_SUFFIX|g" \
  -e "s|\${ASG_NAME}|$ASG_NAME|g" \
  -e "s|\${DB_INSTANCE_ID}|blackfriday-prod-postgres|g" \
  -e "s|\${ELASTICACHE_ID}|blackfriday-prod-redis|g" \
  -e "s|\${WAF_ACL_NAME}|blackfriday-prod-web-acl|g" \
  -e "s|\${AWS_REGION}|us-east-1|g" \
  monitoring/cloudwatch-dashboard.json > /tmp/dashboard-filled.json

aws cloudwatch put-dashboard \
  --dashboard-name BlackFriday-Ops \
  --dashboard-body file:///tmp/dashboard-filled.json

echo "Dashboard: https://console.aws.amazon.com/cloudwatch/home#dashboards:name=BlackFriday-Ops"
```

---

## CloudWatch Alarms

10 alarms are created automatically by `modules/monitoring/` and wired to an SNS email topic:

| Alarm | Metric | Threshold |
|---|---|---|
| ALB ELB 5xx errors | `HTTPCode_ELB_5XX_Count` | > 50 in 60s |
| ALB target 5xx errors | `HTTPCode_Target_5XX_Count` | > 50 in 60s |
| ALB P99 response time | `TargetResponseTime` p99 | > 2s for 2 periods |
| ALB unhealthy hosts | `UnHealthyHostCount` | > 0 for 2 periods |
| ASG CPU high | `CPUUtilization` | > 80% for 2×5min |
| RDS CPU high | `CPUUtilization` | > 80% for 3×5min |
| RDS connections high | `DatabaseConnections` | > 80 for 2×5min |
| RDS free storage low | `FreeStorageSpace` | < 5 GiB |
| ElastiCache CPU high | `EngineCPUUtilization` | > 65% for 3×5min |
| Cache hit rate low | `CacheHits / (CacheHits + CacheMisses)` | < 80% for 3×5min |

To change the alert email: `terraform apply -var="alert_email=you@example.com"`

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
| ACM Certificate | 1 cert | Free |
| SNS + CloudWatch Alarms | 10 alarms + email | ~$1 |
| Secrets Manager | 1 secret | ~$0.40 |
| CloudWatch Logs/Dashboard | Dashboard + logs | ~$5 |
| **Total** | | **~$301/month** |

---

## Key Metrics to Watch During Peak

| Metric | Warning | Critical | Source |
|---|---|---|---|
| ALB P99 latency | > 500ms | > 2000ms | CloudWatch alarm |
| ASG in-service instances | — | = max (20) | CloudWatch alarm |
| RDS connections | > 60 | > 80 | CloudWatch alarm |
| Cache hit rate | < 80% | < 50% | CloudWatch alarm |
| WAF blocked requests | > 1000/min | > 10000/min | WAF dashboard |
| ALB 5XX errors | > 10/min | > 100/min | CloudWatch alarm |
| RDS free storage | < 10GB | < 5GB | CloudWatch alarm |

---

## Troubleshooting

### `terraform apply` fails on RDS Proxy — "Secrets Manager secret not found"
Re-run `terraform apply` — the secret propagation is eventually consistent and succeeds on the second pass.

### EC2 instances launch but health checks fail
- Confirm `app.py` is in S3: `aws s3 ls s3://blackfriday-prod-app-<ACCOUNT_ID>/`
- Confirm IAM role has `s3:GetObject` and `secretsmanager:GetSecretValue`
- Check instance logs via SSM Session Manager: `aws ssm start-session --target <instance-id>`

### GitHub Actions OIDC fails — "Could not load credentials from any providers"
- Confirm the `AWS_DEPLOY_ROLE_ARN` secret is set in GitHub repo Settings → Secrets → Actions
- Confirm the IAM OIDC provider exists: `aws iam list-open-id-connect-providers`
- Check the role trust policy allows `repo:<owner>/<repo>:*` in the `sub` condition

### ACM certificate stuck in `PENDING_VALIDATION`
The certificate needs a DNS CNAME record added at your domain registrar. Run:
```bash
terraform output acm_certificate_validation_options
```
Add the displayed record to your DNS provider. If using Route53, set `route53_zone_id` and Terraform adds the record automatically.

### CloudFront returning stale product data
```bash
aws cloudfront create-invalidation \
  --distribution-id <DISTRIBUTION_ID> \
  --paths "/api/products*"
```

### WAF blocking legitimate requests
Switch the offending rule's `override_action` from `none` to `count` in `terraform/modules/waf/main.tf`, redeploy, and inspect WAF logs to identify the triggering rule before re-enabling block mode.

---

## Teardown

```bash
cd terraform/
# Remove RDS deletion protection first
aws rds modify-db-instance \
  --db-instance-identifier blackfriday-prod-postgres \
  --no-deletion-protection \
  --apply-immediately

terraform destroy
```

> The S3 state bucket and DynamoDB lock table are not managed by Terraform — delete them manually after `terraform destroy` completes.
