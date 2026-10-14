variable "aws_region" {
  type    = string
  default = "eu-north-1"
}

variable "aws_account_id" {
  type    = string
  default = "899088266068"
}

variable "project_name" {
  type    = string
  default = "wtt-demo"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "kubernetes_version" {
  type    = string
  default = "1.36"
}

variable "node_instance_types" {
  type    = list(string)
  default = ["t3.large"]
}

variable "node_desired_size" {
  type    = number
  default = 2
}

variable "node_min_size" {
  type    = number
  default = 2
}

variable "node_max_size" {
  type    = number
  default = 3
}

variable "api_public_access_cidrs" {
  description = "Public IPv4 CIDRs allowed to access EKS API"
  type        = list(string)

  validation {
    condition = (
      length(var.api_public_access_cidrs) > 0 &&
      alltrue([
        for cidr in var.api_public_access_cidrs :
        can(cidrhost(cidr, 0)) && cidr != "0.0.0.0/0"
      ])
    )
    error_message = "Provide restricted CIDRs instead of 0.0.0.0/0."
  }
}