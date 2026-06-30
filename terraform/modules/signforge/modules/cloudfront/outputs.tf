output "domain_name" {
  description = "CloudFront distribution domain name."
  value       = aws_cloudfront_distribution.main.domain_name
}

output "distribution_id" {
  description = "CloudFront distribution ID."
  value       = aws_cloudfront_distribution.main.id
}

output "s3_bucket_name" {
  description = "S3 bucket name for frontend assets."
  value       = aws_s3_bucket.frontend.id
}
