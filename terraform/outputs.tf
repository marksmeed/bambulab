output "alb_prod_dns" {
  description = "Production ALB DNS name"
  value       = aws_lb.prod.dns_name
}

output "alb_staging_dns" {
  description = "Staging ALB DNS name"
  value       = aws_lb.staging.dns_name
}

output "cloudfront_domain" {
  description = "CloudFront distribution domain"
  value       = aws_cloudfront_distribution.prod.domain_name
}

output "rds_prod_endpoint" {
  description = "Production RDS endpoint"
  value       = aws_db_instance.prod.address
}

output "rds_staging_endpoint" {
  description = "Staging RDS endpoint"
  value       = aws_db_instance.staging.address
}

output "efs_prod_id" {
  description = "Production EFS ID"
  value       = aws_efs_file_system.prod.id
}

output "efs_staging_id" {
  description = "Staging EFS ID"
  value       = aws_efs_file_system.staging.id
}

output "acm_validation_records" {
  description = "DNS records to add to traindriversacademy.co.uk to validate TLS certificates"
  value = {
    for dvo in aws_acm_certificate.main.domain_validation_options :
    dvo.domain_name => {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  }
}
