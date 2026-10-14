provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

locals {
  cluster_name = "${var.project_name}-eks"
}

data "terraform_remote_state" "network" {
  backend = "s3"

  config = {
    bucket              = "wtt-demo-tfstate-899088266068-eu-north-1"
    key                 = "network/terraform.tfstate"
    region              = var.aws_region
    use_lockfile        = true
    allowed_account_ids = [var.aws_account_id]
  }
}

data "terraform_remote_state" "iam" {
  backend = "s3"

  config = {
    bucket              = "wtt-demo-tfstate-899088266068-eu-north-1"
    key                 = "iam/terraform.tfstate"
    region              = var.aws_region
    use_lockfile        = true
    allowed_account_ids = [var.aws_account_id]
  }
}

resource "aws_eks_cluster" "main" {
  name     = local.cluster_name
  role_arn = data.terraform_remote_state.iam.outputs.eks_cluster_role_arn
  version  = var.kubernetes_version

  bootstrap_self_managed_addons = false

  vpc_config {
    subnet_ids = concat(
      data.terraform_remote_state.network.outputs.private_subnet_ids,
      data.terraform_remote_state.network.outputs.public_subnet_ids
    )

    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = var.api_public_access_cidrs
  }

  access_config {
    authentication_mode                         = "API_AND_CONFIG_MAP"
    bootstrap_cluster_creator_admin_permissions = true
  }

  upgrade_policy {
    support_type = "STANDARD"
  }

  tags = {
    Name = local.cluster_name
  }
}

resource "aws_eks_addon" "vpc_cni" {
  cluster_name  = aws_eks_cluster.main.name
  addon_name    = "vpc-cni"
  addon_version = "v1.22.4-eksbuild.3"
}

resource "aws_eks_addon" "kube_proxy" {
  cluster_name  = aws_eks_cluster.main.name
  addon_name    = "kube-proxy"
  addon_version = "v1.36.0-eksbuild.25"
}

resource "aws_eks_addon" "coredns" {
  cluster_name  = aws_eks_cluster.main.name
  addon_name    = "coredns"
  addon_version = "v1.14.7-eksbuild.10"

  depends_on = [aws_eks_node_group.main]
}
resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${var.project_name}-nodes"
  node_role_arn   = data.terraform_remote_state.iam.outputs.eks_node_role_arn

  subnet_ids = data.terraform_remote_state.network.outputs.private_subnet_ids

  depends_on = [aws_eks_addon.vpc_cni]

  instance_types = var.node_instance_types
  capacity_type  = "ON_DEMAND"
  disk_size      = 40

  scaling_config {
    desired_size = var.node_desired_size
    min_size     = var.node_min_size
    max_size     = var.node_max_size
  }

  update_config {
    max_unavailable = 1
  }

  tags = {
    Name = "${var.project_name}-nodes"
  }
}
