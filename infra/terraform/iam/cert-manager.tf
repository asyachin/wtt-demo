# DNS-01 permissions for wtt-demo.syachin.de only.

data "aws_iam_policy_document" "cert_manager_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cert_manager" {
  name               = "wtt-demo-cert-manager-role"
  assume_role_policy = data.aws_iam_policy_document.cert_manager_assume.json

  tags = {
    Project = "wtt-demo"
  }
}

data "aws_iam_policy_document" "cert_manager_route53" {
  statement {
    sid       = "ChangeAcmeChallengeTXT"
    effect    = "Allow"
    actions   = ["route53:ChangeResourceRecordSets"]
    resources = ["arn:aws:route53:::hostedzone/Z030020038RZDL2JLFT70"]

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "route53:ChangeResourceRecordSetsRecordTypes"
      values   = ["TXT"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "route53:ChangeResourceRecordSetsNormalizedRecordNames"
      values   = ["_acme-challenge.wtt-demo.syachin.de"]
    }
  }

  statement {
    sid       = "ReadHostedZoneRecords"
    effect    = "Allow"
    actions   = ["route53:ListResourceRecordSets"]
    resources = ["arn:aws:route53:::hostedzone/Z030020038RZDL2JLFT70"]
  }

  statement {
    sid       = "CheckDNSChangeStatus"
    effect    = "Allow"
    actions   = ["route53:GetChange"]
    resources = ["arn:aws:route53:::change/*"]
  }
}

resource "aws_iam_policy" "cert_manager_route53" {
  name   = "wtt-demo-cert-manager-route53"
  policy = data.aws_iam_policy_document.cert_manager_route53.json
}

resource "aws_iam_role_policy_attachment" "cert_manager_route53" {
  role       = aws_iam_role.cert_manager.name
  policy_arn = aws_iam_policy.cert_manager_route53.arn
}

output "cert_manager_role_arn" {
  description = "IAM role for cert-manager EKS Pod Identity"
  value       = aws_iam_role.cert_manager.arn
}
