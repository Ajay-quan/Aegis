# Reference AWS infrastructure for AegisTrace. Review costs (docs/operations/
# DEPLOYMENT.md) and obtain approval before `terraform apply`.
# Out of scope here: the EKS cluster itself, DNS/TLS certificates, the IdP.

locals {
  prefix = "${var.name}-${var.environment}"
  tags   = { Project = var.name, Environment = var.environment, ManagedBy = "terraform" }
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------- network
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  tags                 = merge(local.tags, { Name = local.prefix })
}

resource "aws_subnet" "private" {
  count             = length(var.azs)
  vpc_id            = aws_vpc.main.id
  availability_zone = var.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index)
  tags              = merge(local.tags, { Name = "${local.prefix}-private-${count.index}", Tier = "private" })
}

# ---------------------------------------------------------------- encryption
resource "aws_kms_key" "data" {
  description         = "${local.prefix} data-at-rest (RDS, Redis, S3, secrets)"
  enable_key_rotation = true
  tags                = local.tags
}

# ---------------------------------------------------------------- PostgreSQL
resource "aws_db_subnet_group" "main" {
  name       = local.prefix
  subnet_ids = aws_subnet.private[*].id
  tags       = local.tags
}

resource "aws_security_group" "db" {
  name   = "${local.prefix}-db"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.eks_node_security_group_id]
  }
  tags = local.tags
}

resource "aws_db_instance" "main" {
  identifier                          = local.prefix
  engine                              = "postgres"
  engine_version                      = "17"
  instance_class                      = var.db_instance_class
  allocated_storage                   = var.db_allocated_storage_gb
  storage_encrypted                   = true
  kms_key_id                          = aws_kms_key.data.arn
  db_name                             = "aegistrace"
  username                            = "aegis_owner"
  manage_master_user_password         = true # stored in Secrets Manager, never in state as plaintext
  master_user_secret_kms_key_id       = aws_kms_key.data.arn
  db_subnet_group_name                = aws_db_subnet_group.main.name
  vpc_security_group_ids              = [aws_security_group.db.id]
  publicly_accessible                 = false
  multi_az                            = true
  backup_retention_period             = 14 # enables point-in-time recovery
  deletion_protection                 = true
  copy_tags_to_snapshot               = true
  iam_database_authentication_enabled = true
  performance_insights_enabled        = true
  performance_insights_kms_key_id     = aws_kms_key.data.arn
  skip_final_snapshot                 = false
  final_snapshot_identifier           = "${local.prefix}-final"
  tags                                = local.tags
}

# ---------------------------------------------------------------- Redis
resource "aws_elasticache_subnet_group" "main" {
  name       = local.prefix
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_security_group" "redis" {
  name   = "${local.prefix}-redis"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [var.eks_node_security_group_id]
  }
  tags = local.tags
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id       = local.prefix
  description                = "AegisTrace run dispatch (Redis Streams); PostgreSQL remains source of truth"
  engine                     = "redis"
  node_type                  = var.redis_node_type
  num_cache_clusters         = 2
  automatic_failover_enabled = true
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.data.arn
  transit_encryption_enabled = true
  snapshot_retention_limit   = 3
  tags                       = local.tags
}

# ---------------------------------------------------------------- artifacts
resource "aws_s3_bucket" "artifacts" {
  bucket = "${local.prefix}-artifacts-${data.aws_caller_identity.current.account_id}"
  tags   = local.tags
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration { status = "Enabled" }
}

# ---------------------------------------------------------------- checkpoint anchor
# Append-only, WORM storage for signed checkpoints. For a meaningful trust
# boundary, deploy this in a SEPARATE AWS account administered independently
# of the application account (see docs/cryptography/TRUST_MODEL.md).
resource "aws_s3_bucket" "anchor" {
  bucket              = "${local.prefix}-checkpoint-anchor-${data.aws_caller_identity.current.account_id}"
  object_lock_enabled = true
  tags                = local.tags
}

resource "aws_s3_bucket_versioning" "anchor" {
  bucket = aws_s3_bucket.anchor.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_object_lock_configuration" "anchor" {
  bucket = aws_s3_bucket.anchor.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.anchor_retention_days
    }
  }
}

resource "aws_s3_bucket_public_access_block" "anchor" {
  bucket                  = aws_s3_bucket.anchor.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------------------------------------------------------- secrets (no values here)
resource "aws_secretsmanager_secret" "signing_key" {
  name        = "${local.prefix}/checkpoint-signing-key"
  description = "Ed25519 checkpoint signing key (PEM). Value set out of band by the key ceremony runbook."
  kms_key_id  = aws_kms_key.data.arn
  tags        = local.tags
}

resource "aws_ecr_repository" "app" {
  name                 = local.prefix
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.data.arn
  }
  tags = local.tags
}
