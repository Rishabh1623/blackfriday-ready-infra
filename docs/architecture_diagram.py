"""
BlackFriday-Ready Infrastructure — Architecture Diagram
Run: pip install diagrams && python3 docs/architecture_diagram.py
Output: docs/blackfriday_architecture.png
"""

from diagrams import Diagram, Cluster, Edge
from diagrams.aws.network import CloudFront, ALB, NATGateway, InternetGateway, VPC
from diagrams.aws.compute import EC2, AutoScaling
from diagrams.aws.database import RDS, Elasticache, RDSProxy
from diagrams.aws.security import WAF, SecretsManager
from diagrams.aws.storage import S3
from diagrams.aws.management import Cloudwatch
from diagrams.aws.integration import SNS
from diagrams.aws.general import User, InternetAlt1
from diagrams.onprem.vcs import Github

graph_attr = {
    "fontsize": "14",
    "bgcolor": "white",
    "pad": "0.75",
    "splines": "ortho",
    "nodesep": "0.6",
    "ranksep": "0.8",
}

with Diagram(
    "BlackFriday-Ready Infrastructure",
    filename="docs/blackfriday_architecture",
    outformat="png",
    show=False,
    direction="TB",
    graph_attr=graph_attr,
):
    users = User("Internet Users")
    github = Github("GitHub Actions\n(CI/CD + OIDC)")

    with Cluster("AWS Cloud — us-east-1"):

        # --- CDN + Security Edge ---
        with Cluster("Edge / Global"):
            cf = CloudFront(
                "CloudFront\nPriceClass_100\n/api/products* TTL 300s\n/api/inventory* TTL 0\n/api/checkout* TTL 0"
            )
            waf = WAF(
                "WAF WebACL\nRate Limit 50K/5min\nOWASP CommonRuleSet\nSQLi RuleSet"
            )

        # --- VPC ---
        with Cluster("VPC  10.0.0.0/16"):

            igw = InternetGateway("Internet Gateway")
            nat = NATGateway("NAT Gateway\n(us-east-1a)")

            # Public Subnets — ALB
            with Cluster("Public Subnets (3 AZs)\n10.0.1-3.0/24"):
                alb = ALB(
                    "Application Load Balancer\nHTTP → HTTPS 301\nHTTPS TLS 1.3 (ACM)\nTarget: port 8000"
                )

            # Private Subnets — Compute
            with Cluster("Private Subnets (3 AZs)\n10.0.11-13.0/24"):

                with Cluster("Auto Scaling Group\nmin=2  max=20  desired=2\nWarm Pool: 3 stopped"):
                    ec2_a = EC2("EC2 t3.medium\nFastAPI + Uvicorn\n(AZ-a)")
                    ec2_b = EC2("EC2 t3.medium\nFastAPI + Uvicorn\n(AZ-b)")
                    ec2_c = EC2("EC2 t3.medium\nFastAPI + Uvicorn\n(AZ-c)")
                    asg = AutoScaling(
                        "Scaling Policies\nTarget: 1000 req/inst\nScheduled: 10 @ 19:45 UTC\nScheduled: 2 @ 23:00 UTC"
                    )

                # Data stores
                with Cluster("Data Layer"):
                    rds_proxy = RDSProxy(
                        "RDS Proxy\nMultiplexes 1600+\napp connx → ~85 DB\nTLS required"
                    )
                    rds = RDS(
                        "RDS PostgreSQL 15\ndb.t3.medium\n20 GB gp3 (→100 GB)\nEncrypted | Backups 7d"
                    )
                    redis = Elasticache(
                        "ElastiCache Redis 7.0\n1 Primary + 1 Replica\ncache.t3.micro\nProduct cache TTL 300s"
                    )

                secrets = SecretsManager(
                    "Secrets Manager\nDB credentials\n(user + password JSON)"
                )

            # S3 for app artifacts
            s3_app = S3("S3 App Artifacts\nversioned + encrypted\npublic access blocked")
            s3_state = S3("S3 Terraform State\n+ DynamoDB lock table")

        # --- Monitoring ---
        with Cluster("Monitoring & Alerting"):
            cw = Cloudwatch(
                "CloudWatch\n10 Alarms\nALB 5xx, P99 latency\nASG CPU, RDS CPU\nCache hit rate"
            )
            sns = SNS("SNS Topic\nEmail alerts\nrishabhmadne1623@gmail.com")

    # ----- Edges (traffic flow) -----
    users >> Edge(label="HTTPS") >> cf
    cf >> Edge(label="origin request") >> waf
    waf >> Edge(label="allowed traffic") >> alb
    alb >> Edge(label="port 8000") >> [ec2_a, ec2_b, ec2_c]

    ec2_a >> Edge(label="port 5432\nTLS") >> rds_proxy
    ec2_b >> Edge(label="port 5432\nTLS") >> rds_proxy
    ec2_c >> Edge(label="port 5432\nTLS") >> rds_proxy
    rds_proxy >> Edge(label="port 5432") >> rds

    ec2_a >> Edge(label="port 6379 TLS") >> redis
    ec2_b >> Edge(label="port 6379 TLS") >> redis
    ec2_c >> Edge(label="port 6379 TLS") >> redis

    [ec2_a, ec2_b, ec2_c] >> Edge(label="GetSecretValue") >> secrets
    rds_proxy >> Edge(label="GetSecretValue") >> secrets

    # NAT for outbound
    [ec2_a, ec2_b, ec2_c] >> Edge(label="outbound\nvia NAT") >> nat
    nat >> igw

    # CI/CD
    github >> Edge(label="OIDC + deploy") >> s3_app
    s3_app >> Edge(label="app download\non boot") >> [ec2_a, ec2_b, ec2_c]
    github >> Edge(label="terraform state") >> s3_state

    # Monitoring
    [alb, asg, rds, redis] >> Edge(label="metrics") >> cw
    cw >> Edge(label="alarm") >> sns

    # ALB connection from IGW
    igw >> alb
