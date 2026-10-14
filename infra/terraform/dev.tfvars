# AWS
aws_region     = "eu-north-1"
aws_account_id = "899088266068"

# Project
project_name = "wtt-demo"
environment  = "dev"

# Network
vpc_cidr = "10.42.0.0/16"

availability_zones = [
  "eu-north-1a",
  "eu-north-1b",
]

public_subnet_cidrs = [
  "10.42.0.0/24",
  "10.42.1.0/24",
]

private_subnet_cidrs = [
  "10.42.10.0/24",
  "10.42.11.0/24",
]

# Cost optimization
single_nat_gateway = true
