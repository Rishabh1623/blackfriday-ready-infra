#!/bin/bash
# Packages are pre-installed in the AMI. This script only does environment-specific setup.
set -x

# ── Fetch DB credentials from Secrets Manager ─────────────────────────────────
SECRET=$(aws secretsmanager get-secret-value \
  --secret-id "${db_secret_arn}" \
  --region "${aws_region}" \
  --query SecretString \
  --output text)

DB_USER=$(echo "$SECRET" | python3 -c "import sys,json; print(json.load(sys.stdin)['username'])")
DB_PASS=$(echo "$SECRET" | python3 -c "import sys,json; print(json.load(sys.stdin)['password'])")

# ── Write application directory ───────────────────────────────────────────────
mkdir -p /opt/blackfriday

cat > /opt/blackfriday/.env << ENVEOF
RDS_PROXY_ENDPOINT=${rds_proxy_endpoint}
ELASTICACHE_ENDPOINT=${elasticache_endpoint}
DB_NAME=${db_name}
DB_USER=$${DB_USER}
DB_PASSWORD=$${DB_PASS}
AWS_REGION=${aws_region}
ENVEOF
chmod 600 /opt/blackfriday/.env

# ── Download app.py from S3 with retry ───────────────────────────────────────
for attempt in 1 2 3 4 5; do
  aws s3 cp "s3://${app_bucket}/app.py" /opt/blackfriday/app.py && break
  echo "S3 download attempt $attempt failed, retrying in $${attempt}s..."
  sleep "$${attempt}"
done
chmod 644 /opt/blackfriday/app.py

# ── Create systemd service ────────────────────────────────────────────────────
cat > /etc/systemd/system/blackfriday.service << 'SVCEOF'
[Unit]
Description=BlackFriday FastAPI Application
After=network.target

[Service]
Type=simple
User=nobody
WorkingDirectory=/opt/blackfriday
EnvironmentFile=/opt/blackfriday/.env
ExecStart=/usr/bin/python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable blackfriday
systemctl restart blackfriday
