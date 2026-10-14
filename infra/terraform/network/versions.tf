terraform {
  required_version = ">= 1.16.0, < 1.17.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.68.0"
    }
  }

  backend "s3" {
    bucket              = "wtt-demo-tfstate-899088266068-eu-north-1"
    key                 = "network/terraform.tfstate"
    region              = "eu-north-1"
    encrypt             = true
    use_lockfile        = true
    allowed_account_ids = ["899088266068"]
  }
}
