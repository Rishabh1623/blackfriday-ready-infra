output "sns_topic_arn" {
  description = "ARN of the SNS topic receiving all CloudWatch alarm notifications"
  value       = aws_sns_topic.alerts.arn
}

output "sns_topic_name" {
  value = aws_sns_topic.alerts.name
}
