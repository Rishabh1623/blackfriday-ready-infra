locals {
  name = "${var.project_name}-${var.environment}"

  user_data = base64encode(templatefile("${path.module}/user_data.sh.tpl", {
    rds_proxy_endpoint   = var.rds_proxy_endpoint
    elasticache_endpoint = var.elasticache_endpoint
    db_name              = var.db_name
    db_secret_arn        = var.db_secret_arn
    aws_region           = var.aws_region
    app_bucket           = aws_s3_bucket.app.id
  }))
}

data "aws_caller_identity" "current" {}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ── IAM ────────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "ec2" {
  name = "${local.name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${local.name}-ec2-role" }
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "secrets" {
  name = "${local.name}-ec2-secrets-policy"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [var.db_secret_arn]
    }]
  })
}

resource "aws_iam_role_policy" "s3_app" {
  name = "${local.name}-ec2-s3-policy"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = ["${aws_s3_bucket.app.arn}/app.py"]
    }]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${local.name}-ec2-profile"
  role = aws_iam_role.ec2.name
}

# ── S3 App Artifact Bucket ────────────────────────────────────────────────────

resource "aws_s3_bucket" "app" {
  bucket        = "${local.name}-app-${data.aws_caller_identity.current.account_id}"
  force_destroy = true

  tags = { Name = "${local.name}-app-artifacts" }
}

resource "aws_s3_bucket_versioning" "app" {
  bucket = aws_s3_bucket.app.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "app" {
  bucket = aws_s3_bucket.app.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "app" {
  bucket                  = aws_s3_bucket.app.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "app_py" {
  bucket = aws_s3_bucket.app.id
  key    = "app.py"
  source = var.app_source_path
  etag   = filemd5(var.app_source_path)
}

# ── ALB ───────────────────────────────────────────────────────────────────────

resource "aws_lb" "main" {
  name               = "${local.name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.sg_alb_id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = false

  tags = { Name = "${local.name}-alb" }
}

resource "aws_lb_target_group" "app" {
  name     = "${local.name}-tg"
  port     = 8000
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 15
    matcher             = "200"
  }

  deregistration_delay = 30

  tags = { Name = "${local.name}-tg" }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  # When HTTPS is available, redirect all HTTP traffic to HTTPS (301).
  # Without a certificate, forward directly so HTTP still works for testing.
  default_action {
    type             = var.certificate_arn != "" ? "redirect" : "forward"
    target_group_arn = var.certificate_arn == "" ? aws_lb_target_group.app.arn : null

    dynamic "redirect" {
      for_each = var.certificate_arn != "" ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

# HTTPS listener — created only when a validated ACM certificate is supplied
resource "aws_lb_listener" "https" {
  count = var.certificate_arn != "" ? 1 : 0

  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# ── Launch Template ───────────────────────────────────────────────────────────

resource "aws_launch_template" "app" {
  name_prefix   = "${local.name}-lt-"
  image_id      = var.app_ami_id != "" ? var.app_ami_id : data.aws_ami.al2023.id
  instance_type = var.instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.ec2.name
  }

  network_interfaces {
    associate_public_ip_address = false
    security_groups             = [var.sg_ec2_id]
  }

  # IMDSv2 required — prevents SSRF-based metadata credential theft
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }

  user_data = local.user_data

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name        = "${local.name}-app"
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ── Auto Scaling Group ────────────────────────────────────────────────────────

resource "aws_autoscaling_group" "app" {
  name                = "${local.name}-asg"
  min_size            = var.asg_min_size
  max_size            = var.asg_max_size
  desired_capacity    = var.asg_desired_capacity
  vpc_zone_identifier = var.private_subnet_ids

  launch_template {
    id      = aws_launch_template.app.id
    version = "$Latest"
  }

  target_group_arns         = [aws_lb_target_group.app.arn]
  health_check_type         = "ELB"
  health_check_grace_period = 600

  # Warm pool: pre-initialised stopped instances ready to start in seconds
  warm_pool {
    min_size              = 3
    pool_state            = "Stopped"
    max_group_prepared_capacity = -1

    instance_reuse_policy {
      reuse_on_scale_in = true
    }
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
    }
  }

  tag {
    key                 = "Name"
    value               = "${local.name}-app"
    propagate_at_launch = true
  }

  tag {
    key                 = "Project"
    value               = var.project_name
    propagate_at_launch = true
  }

  tag {
    key                 = "Environment"
    value               = var.environment
    propagate_at_launch = true
  }

  tag {
    key                 = "ManagedBy"
    value               = "Terraform"
    propagate_at_launch = true
  }

  lifecycle {
    ignore_changes = [desired_capacity]
  }
}

# ── Scaling Policies ──────────────────────────────────────────────────────────

resource "aws_autoscaling_policy" "alb_request_count" {
  name                   = "${local.name}-alb-request-tracking"
  autoscaling_group_name = aws_autoscaling_group.app.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      # Format: app/<alb-name>/<alb-id>/targetgroup/<tg-name>/<tg-id>
      resource_label = "${aws_lb.main.arn_suffix}/${aws_lb_target_group.app.arn_suffix}"
    }
    target_value = 1000
  }
}

# Scheduled scale-out at 19:45 UTC — before peak Black Friday traffic
resource "aws_autoscaling_schedule" "scale_out_peak" {
  scheduled_action_name  = "${local.name}-scale-out-peak"
  autoscaling_group_name = aws_autoscaling_group.app.name
  recurrence             = "45 19 * * *"
  desired_capacity       = 10
  min_size               = var.asg_min_size
  max_size               = var.asg_max_size
}

# Scheduled scale-in at 23:00 UTC — after peak subsides
resource "aws_autoscaling_schedule" "scale_in_post_peak" {
  scheduled_action_name  = "${local.name}-scale-in-post-peak"
  autoscaling_group_name = aws_autoscaling_group.app.name
  recurrence             = "0 23 * * *"
  desired_capacity       = 2
  min_size               = var.asg_min_size
  max_size               = var.asg_max_size
}
