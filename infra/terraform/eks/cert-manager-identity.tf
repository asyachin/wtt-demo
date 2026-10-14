# Allow cert-manager to manage DNS-01 challenges through Route53.
# IAM role is managed by the separate Terraform IAM root module.

resource "aws_eks_pod_identity_association" "cert_manager" {
  cluster_name    = "wtt-demo-eks"
  namespace       = "cert-manager"
  service_account = "cert-manager"

  role_arn = "arn:aws:iam::899088266068:role/wtt-demo-cert-manager-role"

  depends_on = [
    aws_eks_addon.pod_identity_agent
  ]
}
