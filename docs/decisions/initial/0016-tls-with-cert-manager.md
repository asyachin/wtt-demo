# 0016 — Terminate TLS in the Cluster, With cert-manager and Let's Encrypt

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | [0008](0008-ingress-and-dns.md) |
| Superseded by | none |

## Context

[ADR 0015](0015-traefik-gateway-api.md) replaces the ALB with Traefik behind a Network Load Balancer. That removes the free part of [ADR 0008](0008-ingress-and-dns.md): an ACM certificate attached to an ALB listener, issued and renewed by AWS at no cost and with no moving parts.

An ACM certificate cannot be exported. Its private key never leaves AWS, so it can only be used by an AWS service such as an ALB, an NLB, or CloudFront. Traefik cannot load it.

So TLS has to be terminated somewhere else, and there are two places it can go.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| cert-manager with Let's Encrypt, Traefik terminates TLS, NLB is pure L4 | One scheme everywhere, including `kind` and a laptop. Fully portable, which is the reason Traefik was chosen. The certificate is a Kubernetes `Secret`, so it is visible and testable from inside the cluster. | cert-manager, a `ClusterIssuer`, and an ACME solver are new components. Let's Encrypt has rate limits. A renewal failure is now the project's outage. |
| ACM on the NLB, Traefik receives plain TCP | No certificate work. AWS renews it. | The scheme differs between `kind` and EKS, so TLS is untested until production. Traefik cannot set HSTS correctly without knowing the scheme. Still AWS-specific, which undercuts the portability argument for Traefik. |
| Self-signed or a private certificate authority | No external dependency, no rate limit | A browser warning on a URL that is on a job application. Unacceptable. |
| CloudFront in front with ACM | Caching, WAF, AWS-managed certificate | A whole content delivery network added to solve a certificate problem, plus another 20 USD per month |

## Decision

cert-manager issues certificates from Let's Encrypt. Traefik terminates TLS on its `8443` entrypoint using the resulting Kubernetes `Secret`, referenced by the `Gateway` listener through `certificateRefs`. The NLB operates at layer 4 and does not terminate anything.

| Setting | Value | Reason |
|---|---|---|
| Challenge type | DNS-01, through Route 53 | Issues a wildcard, works before any public traffic reaches the cluster, and works for a host that is not published at all |
| Certificate | `wtt-demo.syachin.de` and `*.wtt-demo.syachin.de`, one certificate | Matches the ACM certificate that ADR 0008 described, so no routing changes |
| Issuers | Two `ClusterIssuer` objects: `letsencrypt-staging` and `letsencrypt-prod` | Staging is used for every first attempt and for every drill, because production rate limits are low and unforgiving |
| cert-manager IAM | An IRSA role scoped to `route53:ChangeResourceRecordSets` on the `syachin.de` hosted zone only | The same scope ExternalDNS already has |
| Renewal | cert-manager renews at two thirds of the lifetime, so about 30 days before expiry | Leaves 30 days to notice and fix a failure |
| Installed by | Terraform, in the platform module, before Traefik | Traefik cannot serve an HTTPS listener without the `Secret` |

The ACM certificate and its Terraform resource are removed.

## Reasoning

### One scheme everywhere

The reason Traefik was chosen in ADR 0015 was that it behaves the same in `kind` and on EKS, which moves four routing tests into CI. Terminating TLS on the NLB with ACM would partly give that away: `kind` would serve plain HTTP while production served HTTPS, so the TLS path, the redirect, and HSTS would again be untested until Block 07 on live AWS.

With cert-manager the scheme is identical in both places. `kind` uses the staging issuer or a self-signed issuer, EKS uses the production issuer, and everything between the listener and the application is the same object graph. The end-to-end tests can assert on a certificate in `kind`.

### DNS-01, not HTTP-01

DNS-01 is chosen deliberately. HTTP-01 needs the hostname to be publicly reachable on port 80 before a certificate exists, which makes the first issuance depend on the thing it is needed for, and it cannot produce a wildcard. DNS-01 writes a TXT record in Route 53, which is already under IAM control for ExternalDNS, so the same scoped permission pattern is reused. It also means a certificate can be issued for a hostname that is never published, which keeps the option open for the development namespace.

### Two issuers is not optional

Let's Encrypt production allows 50 certificates per registered domain per week and 5 duplicate certificates per week. A debugging session on a misconfigured solver can exhaust the duplicate limit in an afternoon, and then the project waits a week with no certificate. Every first attempt and every disaster recovery drill therefore runs against staging, and only a verified configuration is pointed at production. This is the single most common way to lose a day with cert-manager, and the guard is cheap.

### The cost is accepted with open eyes

The thing ADR 0008 got right was that ACM renewal is somebody else's problem. That is now the project's problem. A renewal failure is a public outage, and the fix is not under AWS's control. The mitigations are a 30-day warning window, an alert on the `Certificate` resource rather than only on the served certificate, and a runbook section. That is strictly worse than ACM and is the price of the portability chosen in ADR 0015.

## Consequences

### Positive

- One TLS scheme in `kind`, on a laptop, and on EKS, so the path is tested before production.
- The certificate is a Kubernetes `Secret`, so its expiry, its chain, and its renewal are visible to `kubectl` and to tests.
- A wildcard means a new subdomain needs no certificate work.
- No dependency on an AWS-only certificate service, which is what portability actually requires.
- cert-manager's IAM scope reuses the ExternalDNS pattern, so there is one thing to reason about.

### Negative

- Certificate renewal is now an operational responsibility, and a failure is a public outage. This is a real regression against ACM and is the main cost of ADR 0015.
- cert-manager is a new component with CRDs, a webhook, and a cainjector. Its webhook being unavailable blocks `Certificate` changes cluster-wide.
- Let's Encrypt rate limits can lock the project out for a week after enough failed attempts. The staging issuer is the guard, and the discipline has to be followed.
- Let's Encrypt is an external dependency for the renewal path. An outage there during a renewal window matters, although the 30-day margin makes it unlikely to matter much.
- The private key now exists in the cluster, as a `Secret` in the `traefik` namespace. With ACM it never existed anywhere reachable. RBAC and the control plane audit log are the mitigation, and the exposure is real.
- A total cluster loss means re-issuing the certificate during recovery, which adds a DNS propagation wait to the disaster recovery time. The drill in Block 13 measures it.
- Route 53 now accepts TXT record writes from a second component, so two controllers write into the same hosted zone.

### Neutral

- Let's Encrypt is free, as ACM was, so there is no cost change.
- A 90-day certificate lifetime instead of ACM's 13 months means renewal happens often enough to be exercised rather than forgotten, which cuts both ways.

## Verification

Block 07:

- `test_certmanager_is_healthy` — the controller, the webhook, and the cainjector are all ready
- `test_staging_certificate_issues` — a `Certificate` against `letsencrypt-staging` reaches `Ready` within 300 seconds
- `test_production_certificate_is_ready` — the real `Certificate` reports `Ready` with both names in its `dnsNames`
- `test_certmanager_iam_is_scoped` — a record write outside the `syachin.de` hosted zone is denied
- `test_served_certificate_is_trusted` — a TLS handshake against `https://wtt-demo.syachin.de` is accepted by a standard trust store and the issuer is Let's Encrypt, not the staging authority

Block 10:

- `CertificateExpiringSoon` now reads the cert-manager `Certificate` expiry through `kube-state-metrics`, not ACM
- `CertificateRenewalFailed` is a new alert on a `Certificate` whose `Ready` condition has been false for an hour, which catches a stuck renewal 30 days before anybody would notice it in a browser

Block 13:

- `test_rebuild_from_nothing` includes certificate re-issuance, and the measured recovery time includes the DNS propagation wait

## Revisit When

Certificate operations cause a real outage, or AWS WAF becomes a requirement. Either one points back to an ALB with ACM, and the Gateway API manifests would move with only the listener TLS block changing.
