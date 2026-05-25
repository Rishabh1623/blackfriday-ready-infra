# BlackFriday-Ready Infrastructure — Architecture Diagram

```mermaid
flowchart TB
    USERS(["🌐 Internet Users"])
    GH(["⚙️ GitHub Actions\nCI/CD · OIDC"])

    subgraph EDGE["Edge / Global"]
        CF["☁️ CloudFront\nPriceClass_100 · IPv6\n/api/products* → TTL 300s\n/api/inventory* → TTL 0\n/api/checkout* → TTL 0"]
        WAF["🛡️ WAF WebACL\nRate Limit: 50K req / 5 min / IP\nAWS Managed: CommonRuleSet\nAWS Managed: SQLiRuleSet"]
    end

    subgraph VPC["VPC  10.0.0.0/16  ·  us-east-1"]

        IGW["🌐 Internet Gateway"]
        NAT["🔁 NAT Gateway\nus-east-1a  ·  Elastic IP"]

        subgraph PUB["Public Subnets — 3 AZs  (10.0.1-3.0/24)"]
            ALB["⚖️ Application Load Balancer\nPort 80 → 301 HTTPS\nPort 443 TLS 1.3 · ACM cert\nHealth: GET /health every 15s"]
        end

        subgraph PRIV["Private Subnets — 3 AZs  (10.0.11-13.0/24)"]

            subgraph ASG["Auto Scaling Group  ·  min=2  max=20  desired=2\nWarm Pool: 3 stopped instances (~30s cold start)"]
                EC2A["🖥️ EC2 t3.medium\nFastAPI + Uvicorn :8000\nAL2023  ·  IMDSv2\nAZ-a"]
                EC2B["🖥️ EC2 t3.medium\nFastAPI + Uvicorn :8000\nAL2023  ·  IMDSv2\nAZ-b"]
                EC2C["🖥️ EC2 t3.medium\nFastAPI + Uvicorn :8000\nAL2023  ·  IMDSv2\nAZ-c"]
            end

            SCALE["📈 Scaling Policies\nTarget tracking: 1000 req/instance\nScheduled OUT: desired=10 @ 19:45 UTC\nScheduled IN:  desired=2  @ 23:00 UTC"]

            subgraph DATA["Data Layer"]
                PROXY["🔀 RDS Proxy\n1600+ app connx → ~85 DB\nPort 5432  ·  TLS required\nborrow_timeout: 120s"]
                RDS["🐘 RDS PostgreSQL 15\ndb.t3.medium\n20 GB gp3 (auto-scale → 100 GB)\nEncrypted · Backups 7d · Deletion protection"]
                REDIS["⚡ ElastiCache Redis 7.0\n1 Primary + 1 Replica  ·  cache.t3.micro\nPort 6379  ·  TLS + at-rest encryption\nProduct catalog TTL: 300s  ·  Auto-failover"]
            end

            SM["🔑 Secrets Manager\nblackfriday/rds/credentials\nJSON: username + password"]
        end

        subgraph S3["S3 Buckets"]
            S3APP["📦 App Artifacts\nversioned · encrypted\npublic access blocked"]
            S3TF["🗄️ Terraform State\n+ DynamoDB lock table"]
        end

    end

    subgraph MON["Monitoring & Alerting"]
        CW["📊 CloudWatch\n10 Alarms:\nALB 5xx errors · ALB target 5xx · P99 latency > 2s\nUnhealthy hosts · ASG CPU > 80%\nRDS CPU > 80% · RDS connections > 80 · RDS storage < 5GB\nCache CPU > 65% · Cache hit rate < 80%"]
        SNS["📧 SNS Topic\nEmail → rishabhmadne1623@gmail.com"]
    end

    %% ── Traffic flow ──────────────────────────────────────────────
    USERS -->|"HTTPS"| CF
    CF -->|"origin request"| WAF
    WAF -->|"allowed traffic"| IGW
    IGW --> ALB
    ALB -->|"port 8000"| EC2A
    ALB -->|"port 8000"| EC2B
    ALB -->|"port 8000"| EC2C

    %% ── Database path ─────────────────────────────────────────────
    EC2A -->|"5432 TLS"| PROXY
    EC2B -->|"5432 TLS"| PROXY
    EC2C -->|"5432 TLS"| PROXY
    PROXY -->|"5432"| RDS

    %% ── Cache path ────────────────────────────────────────────────
    EC2A -->|"6379 TLS"| REDIS
    EC2B -->|"6379 TLS"| REDIS
    EC2C -->|"6379 TLS"| REDIS

    %% ── Secrets ───────────────────────────────────────────────────
    EC2A -->|"GetSecretValue"| SM
    EC2B -->|"GetSecretValue"| SM
    EC2C -->|"GetSecretValue"| SM
    PROXY -->|"GetSecretValue"| SM

    %% ── Outbound via NAT ──────────────────────────────────────────
    EC2A -.->|"outbound"| NAT
    EC2B -.->|"outbound"| NAT
    EC2C -.->|"outbound"| NAT

    %% ── ASG scaling ───────────────────────────────────────────────
    SCALE -.-> ASG

    %% ── CI/CD ─────────────────────────────────────────────────────
    GH -->|"OIDC + upload artifact"| S3APP
    GH -->|"terraform state"| S3TF
    S3APP -->|"download on boot\n(user_data.sh)"| EC2A
    S3APP -->|"download on boot"| EC2B
    S3APP -->|"download on boot"| EC2C

    %% ── Monitoring ────────────────────────────────────────────────
    ALB -->|"metrics"| CW
    ASG -->|"metrics"| CW
    RDS -->|"metrics"| CW
    REDIS -->|"metrics"| CW
    CW -->|"alarm"| SNS

    %% ── Styles ────────────────────────────────────────────────────
    classDef edge    fill:#FF9900,stroke:#232F3E,color:#fff,font-weight:bold
    classDef compute fill:#ED7100,stroke:#232F3E,color:#fff
    classDef db      fill:#3F48CC,stroke:#232F3E,color:#fff
    classDef storage fill:#7AA116,stroke:#232F3E,color:#fff
    classDef security fill:#DD3522,stroke:#232F3E,color:#fff
    classDef monitor fill:#E7157B,stroke:#232F3E,color:#fff
    classDef network fill:#8C4FFF,stroke:#232F3E,color:#fff
    classDef user    fill:#232F3E,stroke:#FF9900,color:#fff

    class CF,WAF edge
    class ALB,EC2A,EC2B,EC2C,ASG compute
    class RDS,REDIS,PROXY db
    class S3APP,S3TF storage
    class SM security
    class CW,SNS monitor
    class IGW,NAT,VPC network
    class USERS,GH user
```

## Request Flow

| Step | Path | Notes |
|------|------|-------|
| 1 | Users → CloudFront | TLS at edge, geo-distributed |
| 2 | CloudFront → WAF | Rate limit + OWASP rule enforcement |
| 3 | WAF → ALB | Only allowed traffic reaches VPC |
| 4 | ALB → EC2 (ASG) | Round-robin across 2–20 instances |
| 5 | EC2 → RDS Proxy → RDS | Connection multiplexing, TLS, Secrets Manager auth |
| 6 | EC2 → ElastiCache Redis | Product catalog cached 300s; inventory/checkout bypass |
| 7 | Metrics → CloudWatch → SNS | 10 alarms, email notification on breach |

## Caching Strategy

| Path | CloudFront TTL | Redis TTL | Notes |
|------|---------------|-----------|-------|
| `/api/products*` | 300s | 300s | Two-layer cache |
| `/api/inventory*` | 0 (bypass) | — | Always real-time |
| `/api/checkout*` | 0 (bypass) | — | Always real-time |

## Scaling Configuration

| Trigger | Action |
|---------|--------|
| ALB requests > 1000/instance | Target tracking scale-out |
| Daily 19:45 UTC | Pre-scale to 10 instances (Black Friday peak) |
| Daily 23:00 UTC | Scale-in to 2 instances |
| Warm pool | 3 stopped instances → online in ~30s |
