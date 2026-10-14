terraform {
  backend "s3" {
    bucket       = "wtt-demo-tfstate-899088266068-eu-north-1"
    key          = "bootstrap/terraform.tfstate"
    region       = "eu-north-1"
    encrypt      = true
    use_lockfile = true
  }
}
