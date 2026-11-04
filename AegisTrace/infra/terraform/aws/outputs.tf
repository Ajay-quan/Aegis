output "db_endpoint" { value = aws_db_instance.main.address }
output "db_master_secret_arn" { value = aws_db_instance.main.master_user_secret[0].secret_arn }
output "redis_endpoint" { value = aws_elasticache_replication_group.main.primary_endpoint_address }
output "artifacts_bucket" { value = aws_s3_bucket.artifacts.bucket }
output "anchor_bucket" { value = aws_s3_bucket.anchor.bucket }
output "signing_key_secret_arn" { value = aws_secretsmanager_secret.signing_key.arn }
output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
