# Block 03 — Public HTTPS

| Field | Value |
|---|---|
| Status | `CLOSED` |
| Branch | `block/03-public-https`, merged as `71f0e0a`; corrective fix `6ea8755` |
| Depends on | Block 02 |
| Next | Block 04 |
| Report type | **Retrospective reconstruction**, written 15 October 2026 from the code, the commit history and external verification |

## Goal

Make the demonstration reachable from the internet over HTTPS with a certificate a browser trusts, using automated issuance and the narrowest DNS permissions that can work.

## Observed implementation

| Commit | Subject |
|---|---|
| `71f0e0a` | `feat(platform): expose demo over trusted HTTPS with Route53 DNS-01` |
| `6ea8755` | `fix(gateway): redirect result path to trailing slash` — corrective, found after the block was believed complete |

### What was built

1. **cert-manager** installed by Helm. Chart version not recorded — a reproducibility gap carried into [Block 05](05-gitops.md) as scope item 05-B.
2. **An IAM role with a least-privilege Route 53 policy**, `infra/terraform/iam/cert-manager.tf`. Scoped by three condition keys: action limited to `route53:ChangeResourceRecordSets`, record type restricted to `TXT`, and record name restricted to exactly `_acme-challenge.wtt-demo.syachin.de`, in one hosted zone. A compromised cert-manager pod can manipulate one TXT record name and nothing else.
3. **A Pod Identity association**, `infra/terraform/eks/cert-manager-identity.tf`, binding that role to the `cert-manager` service account, with `depends_on` the Pod Identity agent add-on.
4. **Two `ClusterIssuer` objects**, staging and production, each with a DNS-01 Route 53 solver selected by `dnsNames`.
5. **Two `Certificate` objects.** The staging certificate was issued first to prove the solver, then the production certificate. This is the correct order: Let's Encrypt production permits five duplicate certificates per week, and a misconfigured solver exhausts that quota in an afternoon.
6. **Public exposure**, `k8s/platform/traefik/values-public.yaml`: the Traefik Service switched to `type: LoadBalancer` with annotations requesting an internet-facing NLB in the two public subnets, named by subnet ID.
7. **A Route 53 A ALIAS record**, `infra/terraform/iam/dns-demo.tf`, pointing at the generated NLB hostname.

### The corrective fix

After the block was believed complete, a browser revealed that `/result` without a trailing slash was broken. The route matched and the server returned the document with HTTP 200, but the browser resolved the page's relative asset paths against `/` rather than `/result/`, so the JavaScript was requested from the wrong location and never loaded. The page appeared to render and every `curl` check passed.

`6ea8755` added an `HTTPRoute` named `result-redirect` with an `Exact` match on `/result` and a `RequestRedirect` filter returning 301 to `/result/`.

**This is the most instructive event in the project.** The block's acceptance criteria were satisfied by HTTP status codes, and the defect was invisible to them. That gap is the entire reason [Block 04](04-demo-quality-gate.md) exists and why its criteria require browser-level observation. Recorded in [../lessons.md](../lessons.md).

## Acceptance criteria and evidence

Verified externally on 15 October 2026 from a workstation outside AWS. These results are reproducible by any reader.

| # | Criterion | Verification | Result |
|---|---|---|---|
| 1 | The name resolves to the load balancer | `dig +short wtt-demo.syachin.de` | **Pass** — `13.61.87.220`, `13.60.127.160`, one per availability zone |
| 2 | The vote page is served over HTTPS | `curl -o /dev/null -w '%{http_code}' https://wtt-demo.syachin.de/` | **Pass** — 200 |
| 3 | The certificate is trusted and from Let's Encrypt production | `openssl s_client -connect wtt-demo.syachin.de:443 -servername wtt-demo.syachin.de` | **Pass** — `CN=wtt-demo.syachin.de`, issuer `C=US, O=Let's Encrypt, CN=YR2`, valid 2026-10-14 to 2027-01-12 |
| 4 | The result page is served | `curl -o /dev/null -w '%{http_code}' https://wtt-demo.syachin.de/result/` | **Pass** — 200 |
| 5 | `/result` redirects to `/result/` | `curl -o /dev/null -w '%{http_code} %{redirect_url}' https://wtt-demo.syachin.de/result` | **Pass** — 301 to `https://wtt-demo.syachin.de/result/` |
| 6 | Result page assets load from the correct path | `curl -o /dev/null -w '%{http_code}' https://wtt-demo.syachin.de/result/app.js` | **Pass** — 200 |
| 7 | The Socket.IO endpoint is reachable through the Gateway | `curl 'https://wtt-demo.syachin.de/result/socket.io/?EIO=4&transport=polling'` | **Pass** — 200 |
| 8 | Browser functionality of the result page | Operator observation | **Operator-confirmed** at the time of the work |
| 9 | Certificate `Ready=True`, Gateway `Programmed=True` | `kubectl` | **Requires operator verification** — not recorded |
| 10 | NLB target health | AWS API | **Requires operator verification** — not recorded |

Verification commands, with expected output, are collected in [../operations/verify.md](../operations/verify.md).

### Outstanding operator verification

```bash
kubectl -n traefik get certificate
kubectl -n traefik describe certificate wtt-demo | tail -20
kubectl -n traefik get gateway traefik-gateway -o wide
kubectl -n traefik get svc traefik
aws elbv2 describe-target-health --target-group-arn <arn> --region eu-north-1
```

## Deviations from plan

| Planned | Actual | Recorded in |
|---|---|---|
| Wildcard certificate `*.wtt-demo.syachin.de` | Single name only. Externally confirmed: the SAN list contains one entry. | [../architecture.md](../architecture.md#tls) |
| HTTP-to-HTTPS redirect via a `RequestRedirect` filter | **Not implemented.** Port 80 answers 200 in plaintext, externally confirmed. | [Block 04](04-demo-quality-gate.md) |
| Browser security headers via `ResponseHeaderModifier` | **Not implemented**, externally confirmed absent | [Block 04](04-demo-quality-gate.md) |
| Proxy Protocol v2 for real client addresses | Not configured | Deferred |
| ExternalDNS managing the record from the Gateway | A Terraform record with the NLB hostname written in as a literal | [ADR 0017](../decisions/0017-terraform-multi-root.md), [../lessons.md](../lessons.md) |
| Certificate renewal monitored by an alert | No monitoring exists. A failed renewal would be noticed when the certificate expired. | Block 08 |

The DNS record deviation is the most consequential. Terraform owns the record but the alias target is a value Kubernetes generated. If the Traefik Service is recreated, AWS issues a new NLB hostname, the record keeps pointing at the old one, and the site goes down with no error visible in either Terraform or Kubernetes. `terraform plan` stays empty throughout.

## Risks and limitations after this block

- **HTTP serves plaintext.** No redirect. A visitor typing the hostname without a scheme gets an unencrypted page.
- **No security headers.** No HSTS, so a browser will not remember to prefer HTTPS.
- **`server: gunicorn`** is exposed in responses.
- **The hardcoded NLB hostname** is a silent single point of failure for DNS.
- **Nothing monitors the certificate.** No alert on renewal failure.
- **Traefik runs one replica** with no PodDisruptionBudget. Its loss is a total outage of the demonstration.
- The mixed-content defect on the vote page, D5, was present throughout this block and was not detected by any criterion here. Addressed in Block 04.

## Definition of Done

- [x] Public HTTPS with a trusted production certificate, externally verified
- [x] Least-privilege DNS-01 permissions
- [x] Pod Identity instead of static credentials
- [x] All three routing behaviours correct, externally verified
- [x] Browser functionality of the result page confirmed by the operator
- [x] No secret in the repository
- [x] Branch merged into `dev`, `71f0e0a` plus `6ea8755`
- [x] Status `CLOSED`
- [ ] **In-cluster certificate and Gateway status recorded as evidence — outstanding**
