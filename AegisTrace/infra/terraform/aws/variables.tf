variable "name" {
  type    = string
  default = "aegistrace"
}
variable "environment" { type = string }
variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}
variable "azs" { type = list(string) }
variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}
variable "db_allocated_storage_gb" {
  type    = number
  default = 50
}
variable "redis_node_type" {
  type    = string
  default = "cache.t4g.small"
}
variable "anchor_retention_days" {
  description = "Object Lock COMPLIANCE retention for anchored checkpoints. Cannot be shortened once written."
  type        = number
  default     = 2555
}
variable "eks_node_security_group_id" {
  description = "Security group of the (separately managed) EKS nodes running API/workers."
  type        = string
}
