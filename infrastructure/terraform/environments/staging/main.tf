# Remote state with locking; the bucket/table are bootstrapped manually once.
terraform {
  backend "s3" {
    bucket       = "CHANGE-ME-aegistrace-tfstate"
    key          = "staging/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" { region = "us-east-1" }

module "aegistrace" {
  source                     = "../../aws"
  environment                = "staging"
  azs                        = ["us-east-1a", "us-east-1b"]
  eks_node_security_group_id = var.eks_node_security_group_id
}

variable "eks_node_security_group_id" { type = string }
