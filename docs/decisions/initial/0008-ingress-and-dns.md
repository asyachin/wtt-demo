# 0008 — One ALB, ACM, and ExternalDNS

| Field | Value |
|---|---|
| Status | Superseded by [0015](0015-traefik-gateway-api.md) and [0016](0016-tls-with-cert-manager.md) |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | [0015](0015-traefik-gateway-api.md) for routing, [0016](0016-tls-with-cert-manager.md) for TLS |

This record considered only Ingress-based options. It did not consider the Gateway API and it did not consider Traefik, which was an omission rather than a rejection. The text below is kept unchanged, as the record of what was decided and why, before that gap was found. The routing decision is now [0015](0015-traefik-gateway-api.md) and the TLS decision is now [0016](0016-tls-with-cert-manager.md).

The routing rules themselves survive unchanged. What changed is the implementation and the certificate authority.

## Context

Three things need to be reachable over HTTPS from the internet: the voting page, the result page, and Grafana. The voting and result pages share a hostname and differ by path. Grafana has its own hostname.

The hosted zone `syachin.de` already exists in Route 53. A load balancer costs about 18 USD per month, so the number of load balancers matters.

The application has two routing constraints that are easy to get wrong. The `result` service serves its websocket on `/result/socket.io` rather than the default `/socket.io`. The `vote` page is served at `/` and posts to `/`, and its template has a hardcoded `<base href="/index.html">`, so it cannot be moved behind a path prefix without changing the template.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| AWS Load Balancer Controller with an ALB | Native AWS integration. TLS terminated by the ALB with a free ACM certificate. Access logs, WAF, and OpenID Connect authentication available if needed. One component. | AWS-specific. Each `Ingress` creates its own ALB unless they are grouped. |
| ingress-nginx with a Network Load Balancer | Portable, rich annotations including basic authentication, one load balancer by default | TLS has to be terminated in the cluster, so the certificate must be in the cluster, which means cert-manager and another moving part. Another workload to run and monitor. |
| An ALB per hostname | Simplest configuration | Two load balancers, so about 36 USD per month instead of 18 |

## Decision

The AWS Load Balancer Controller creates one internet-facing ALB, shared by all `Ingress` objects through an `IngressGroup` named `wtt-demo`.

TLS is terminated at the ALB with an ACM certificate covering `wtt-demo.syachin.de` and `*.wtt-demo.syachin.de`, requested by Terraform with DNS validation. HTTP is redirected to HTTPS by the ALB. The minimum TLS version is 1.2.

Routing:

| Host | Path | Service |
|---|---|---|
| `wtt-demo.syachin.de` | `/` | `vote`, port 80 |
| `wtt-demo.syachin.de` | `/result` | `result`, port 80 |
| `grafana.wtt-demo.syachin.de` | `/` | `grafana`, port 3000 |

ExternalDNS writes the records into the existing `syachin.de` hosted zone, using an IRSA role scoped to that zone only.

Traffic between the ALB and the pods is plain HTTP inside the VPC private subnets.

## Reasoning

The `IngressGroup` is what makes one load balancer serve three routes from separate `Ingress` objects in separate namespaces. That halves the load balancer cost and keeps the certificate count at one.

Terminating TLS at the ALB removes cert-manager from the design. ACM issues and renews the certificate automatically and for free, and the renewal is AWS's problem rather than a CronJob that can fail quietly. The one risk, that automatic renewal does not happen, is covered by the `CertificateExpiringSoon` alert.

ingress-nginx was genuinely close, because its basic authentication annotation would have made publishing Prometheus easy. It was rejected because it brings the certificate into the cluster, which brings cert-manager, which brings a `ClusterIssuer`, an ACME account, and a solver, all to reach the same place ACM reaches with one Terraform resource. The Prometheus problem is solved differently instead, in [0009](0009-observability.md).

The path rules follow the application rather than fighting it. A `/result` prefix rule covers both the page and `/result/socket.io`, so the websocket works without a special rule. Narrowing that rule to `/socket.io`, which is the instinctive thing to do, would break live updates while leaving the page working, and that is a confusing failure. It is written into the architecture document and the runbook for that reason.

`vote` stays at `/` because its template cannot move. Changing the template is application work that this project is not doing, and the root path is where a voting page belongs anyway.

Plain HTTP between the ALB and the pods is a deliberate limit. The traffic stays inside private subnets in one VPC. Encrypting it would mean a certificate in every pod and a service mesh to manage them, which is a large amount of machinery for a demonstration. The limit is stated rather than hidden.

## Consequences

### Positive

- One load balancer, about 18 USD per month.
- One certificate, issued and renewed by AWS at no cost.
- DNS records are created and removed automatically, so a deleted `Ingress` does not leave a stale record.
- HTTP to HTTPS redirect and the TLS version floor are handled by the ALB, not by application code.
- ALB access logs, WAF, and OpenID Connect authentication are available later without changing the design.

### Negative

- The design is AWS-specific. Moving to another cloud or to a private Kubernetes platform means replacing the ingress layer. The README claims the operational patterns transfer, and this is the part that least does.
- Traffic between the ALB and the pods is unencrypted. Acceptable inside a private VPC, and stated as a limitation.
- An `IngressGroup` couples three otherwise independent objects. A malformed annotation on one `Ingress` can affect the whole group, and the error appears in the controller log rather than on the object.
- The ALB is created by the controller rather than by Terraform, so `terraform destroy` does not remove it. Deleting the `Ingress` objects before destroying is a required first step in the teardown procedure, and forgetting it leaves a load balancer billing by the hour.
- Subnet tagging decides whether this works at all. Without `kubernetes.io/role/elb` on the public subnets the controller cannot place the ALB, and the error message does not say so clearly. The tags are set in the network module and checked by a test.
- The wildcard certificate covers one level only, so `a.b.wtt-demo.syachin.de` is not covered. Nothing needs it.

### Neutral

- Grafana gets its own hostname rather than a path, because Grafana behind a path prefix needs its `root_url` set and gets its redirects wrong in ways that waste an afternoon. A subdomain is free under the wildcard certificate.

## Verification

- `test_subnet_tags_for_load_balancer` in Block 06.
- `test_sample_ingress_creates_a_load_balancer`, `test_sample_ingress_creates_a_dns_record`, and `test_sample_ingress_serves_valid_tls` in Block 07, using a throwaway `Ingress` that proves the whole edge path before the application depends on it.
- `test_throwaway_objects_cleaned_up` in Block 07, which confirms that deleting an `Ingress` removes both the ALB and the DNS record.
- `test_ingress_routes_result_socketio` in Block 05.
- `test_http_redirects_to_https` and `test_tls_version_floor` in Block 12.

## Revisit When

Encryption inside the VPC becomes a requirement, or the platform has to move off AWS. Either one replaces the ingress layer rather than adjusting it.
