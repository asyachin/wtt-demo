resource "aws_route53_record" "wtt_demo" {
  zone_id = "Z030020038RZDL2JLFT70"
  name    = "wtt-demo.syachin.de"
  type    = "A"

  alias {
    name                   = "ab6ca8d8903fc411db48922a559fdd15-f9a53d15b6b1bfdf.elb.eu-north-1.amazonaws.com"
    zone_id                = "Z1UDT6IFJ4EJM"
    evaluate_target_health = false
  }
}
