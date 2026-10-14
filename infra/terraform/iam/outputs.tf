output "eks_cluster_role_arn" {
  value = aws_iam_role.eks_cluster.arn
}

output "eks_node_role_arn" {
  value = aws_iam_role.eks_node.arn
}

output "ebs_csi_role_arn" {
  value = aws_iam_role.ebs_csi.arn
}
