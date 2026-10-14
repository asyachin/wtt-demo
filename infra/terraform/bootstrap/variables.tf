variable "aws_region" {
  type    = string
  default = "eu-north-1"
}

variable "state_bucket_name" {
  description = "Globally unique S3 bucket for Terraform state"
  type        = string
}