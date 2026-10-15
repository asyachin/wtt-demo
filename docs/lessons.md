# Operational lessons

Knowledge produced by building this platform. Each item is here because it cost time, caused a defect, or would mislead the next engineer.

## HTTP 200 does not prove the page works

Two defects in this project returned HTTP 200 for the full lifetime of the problem.

**`/result` without a trailing slash.** The route matched, the server returned the HTML document, and the status was 200. But the browser resolves a page's relative asset paths against the request path. At `/result`, the browser treated `/` as the base and requested `/app.js` instead of `/result/app.js`. Those requests 404'd, the JavaScript never ran, and the results page stayed empty. Every `curl` check passed.

The fix was a dedicated `HTTPRoute` with an `Exact` match on `/result` and a `RequestRedirect` filter issuing a 301 to `/result/` — commit `6ea8755`.

**Mixed content on the vote page.** The page loaded jQuery from `http://code.jquery.com/...` while being served over HTTPS. Browsers block mixed active content silently from the server's point of view: the document is 200, the script request never leaves the browser, and nothing appears in any server log. The voted-state highlight simply stopped working. Fixed in `9a9bb9e`.

What follows for acceptance criteria:

- A status code proves the server answered. It proves nothing about rendering, assets, or JavaScript.
- A document-level check must be accompanied by an asset-level check, and by a browser observation with the console open.
- Mixed content can be caught mechanically without a browser by extracting every `src` and `href` from the served HTML and asserting none begins with `http://`.

Note the distinction: `http://host/path` on an HTTPS page is blocked. A **protocol-relative** `//host/path` is not — it resolves to HTTPS. The project no longer has either kind: the v0.8.0 interface redesign removed every third-party asset reference and the page now serves nothing but its own origin.

The more durable fix, applied in that redesign, was not correcting a URL but **removing the client-side code entirely**. The voted-state highlight used to be set by jQuery after the page loaded; it is now rendered server-side with Jinja, `{% if vote == 'a' %}selected{% endif %}`. A page with no JavaScript cannot have its JavaScript blocked, and no CDN outage can affect it. When a defect is caused by a dependency, removing the dependency is worth considering before patching the reference to it.

## Writing an acceptance criterion the application cannot satisfy

The first draft of the Block 04 criteria required that after submitting a vote and **reloading** the page, the chosen option is still highlighted. Reading the source showed that is impossible: `vote` is assigned only inside `if request.method == "POST"`, so the highlight renders on the POST response and never on a subsequent GET.

Had the criterion been written without reading the source, it would have failed forever and the work would have looked broken when it was correct. **Verify what the application actually does before specifying what it must do.**

## Terraform ownership and Kubernetes ownership are different things

The clearest example in this project is the public DNS record.

The Traefik `Service` is of type `LoadBalancer`, so **Kubernetes** asks AWS for a Network Load Balancer and AWS generates its hostname. The Route 53 record that points at it is managed by **Terraform**, with the hostname written in as a literal:

```hcl
# infra/terraform/iam/dns-demo.tf
alias {
  name    = "ab6ca8d8903fc411db48922a559fdd15-f9a53d15b6b1bfdf.elb.eu-north-1.amazonaws.com"
  zone_id = "Z1UDT6IFJ4EJM"
}
```

Terraform now depends on a value it does not own and cannot compute. If the Traefik release is reinstalled or the `Service` is recreated, AWS issues a new NLB with a new hostname, the Route 53 record keeps pointing at the old one, and the site goes down with no error anywhere in Terraform or Kubernetes. `terraform plan` stays empty, because from Terraform's view nothing changed.

Consequences worth carrying forward:

- Decide deliberately which system owns each object, and write it down. The ownership table in [architecture.md](architecture.md#ownership-boundaries) exists for this reason.
- Where one system must consume a value the other generates, either close the loop with a controller such as `external-dns`, or accept a documented manual step. Do not leave a hardcoded literal with no note.
- `terraform destroy` does not remove resources Kubernetes created. The NLB here survives it. That reverses the usual teardown order.

## Pod Identity is simpler than IRSA, and simpler is safer

Both give a pod an IAM role without static credentials. IRSA needs an IAM OIDC provider for the cluster, a trust policy templated with the provider URL, an exact `sub` claim naming the namespace and service account, and an `aud` condition. Each is a place to make a mistake, and the failure mode is an opaque `AccessDenied` from inside a controller pod.

Pod Identity replaces all of it with a trust policy on a service principal:

```hcl
principals {
  type        = "Service"
  identifiers = ["pods.eks.amazonaws.com"]
}
actions = ["sts:AssumeRole", "sts:TagSession"]
```

The binding of role to service account moves out of the trust policy and into an explicit association resource, which is both easier to read and easier to audit:

```hcl
resource "aws_eks_pod_identity_association" "cert_manager" {
  cluster_name    = "wtt-demo-eks"
  namespace       = "cert-manager"
  service_account = "cert-manager"
  role_arn        = "arn:aws:iam::...:role/wtt-demo-cert-manager-role"
}
```

Two practical notes. The `eks-pod-identity-agent` add-on must exist before any association works, which is why both associations declare `depends_on` against it. And the association names a service account that a Helm chart creates later, so the association can be applied before the consumer exists and will simply start working when it appears.

## DNS-01 with genuinely least-privilege permissions

Most cert-manager guides grant `route53:ChangeResourceRecordSets` on a whole hosted zone. That lets a compromised cert-manager pod rewrite any record in the zone, including the record pointing at the demonstration, and including records for unrelated projects sharing the zone.

Three IAM condition keys narrow it to exactly the one thing the solver needs:

```hcl
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
```

`route53:GetChange` still needs `change/*`, because change IDs are generated per request and cannot be predicted. That is an accepted and documented exception rather than a gap.

A second benefit of DNS-01 is architectural: issuance and renewal do not require inbound HTTP. The planned HTTP-to-HTTPS redirect therefore needs no exemption for `/.well-known/acme-challenge/`, which is a common source of breakage when a redirect is added to an HTTP-01 setup.

Always use the Let's Encrypt **staging** issuer first. Production allows five duplicate certificates per week, and a misconfigured solver burns that in an afternoon, after which the certificate cannot be issued at all for days. This project has both a staging and a production `ClusterIssuer` for exactly that reason.

## How HTTPS actually reaches a pod here

```
Browser ──TLS──> NLB (layer 4, no termination) ──TCP──> Traefik ──plain HTTP──> Pod
                                                          │
                                                          └─ TLS terminates here,
                                                             using Secret wtt-demo-tls
```

The NLB does not terminate TLS and does not understand HTTP. It forwards TCP. That has three consequences that surprise people:

1. **The certificate lives in the cluster**, as a Kubernetes Secret, not in ACM. An ACM certificate cannot be exported, so Traefik could never use one. That single fact is why cert-manager is in this architecture at all.
2. **Traefik cannot tell HTTP from HTTPS on a single port.** The NLB adds no `X-Forwarded-Proto`, because layer 4 has no headers. This is why there are two entrypoints, `web:8000` and `websecure:8443`, mapped from ports 80 and 443. A single entrypoint with a redirect rule would redirect HTTPS traffic to itself and loop.
3. **Traefik sees NLB addresses, not client addresses**, unless Proxy Protocol v2 is enabled on both the target group and the entrypoint. Enabling it on one side only breaks all traffic. It is not enabled here, so access logs show infrastructure addresses.

## Gateway API: three filters that are easy to confuse

| Need | Mechanism | What it does |
|---|---|---|
| Send the browser somewhere else | `RequestRedirect` | Returns 301 or 302. The browser makes a second request. The address bar changes. |
| Change the path the backend receives | `URLRewrite` | Proxies internally. The browser sees nothing and the address bar does not change. |
| Change response headers | `ResponseHeaderModifier` | Sets, adds or removes headers on the way back. |

Both of the first two are in use, and for different reasons.

```yaml
# Browser-visible: /result -> /result/ so relative assets resolve correctly
- matches: [{ path: { type: Exact, value: /result } }]
  filters:
    - type: RequestRedirect
      requestRedirect:
        path: { type: ReplaceFullPath, replaceFullPath: /result/ }
        statusCode: 301

# Invisible: strip the /result prefix because the app serves from root
- matches: [{ path: { type: PathPrefix, value: /result } }]
  filters:
    - type: URLRewrite
      urlRewrite:
        path: { type: ReplacePrefixMatch, replacePrefixMatch: / }
```

A redirect would have been wrong for the second case — the browser would end up at `/`, which is the vote page. A rewrite would have been wrong for the first — the relative-path problem happens in the browser, so the browser has to be told the correct URL.

**Match specificity matters.** `/result/socket.io` is matched by a separate, more specific rule that carries **no** rewrite, because the Node.js service genuinely serves its websocket at that path. Gateway API evaluates the more specific path first. Collapsing the two rules into one, which the original plan assumed was possible, would rewrite the websocket path and break live updates while leaving the page working — a failure that looks like a websocket problem and is actually a routing problem.

## EBS-backed persistence, and the zone it pins you to

PostgreSQL runs as a StatefulSet with a `volumeClaimTemplates` entry. On a pod restart, the EBS volume is detached and reattached to the new pod, and the data survives. This was verified by the operator in Block 02.

Two properties of EBS shape the design:

- **A volume exists in one availability zone.** The pod can therefore only ever be scheduled in that zone. If the zone is short of capacity, the pod does not start elsewhere — it stays `Pending`.
- **`volumeBindingMode: WaitForFirstConsumer` is not optional.** With immediate binding, the volume is created before the scheduler has picked a node, so it can land in a zone where the pod cannot be placed, producing a permanently `Pending` pod with a perfectly healthy volume.

The dangerous part is the reclaim policy. The `gp3` StorageClass uses `reclaimPolicy: Delete`, so deleting the PVC destroys the volume and all voting data. A `Retain` policy protects against accidental deletion — but **`Retain` is not a backup.** It does nothing about corruption, a bad migration, or deletion of the volume itself. Both protections are needed and neither exists yet; see [roadmap.md](roadmap.md#next-block).

## VPC CNI pod density, not CPU, sizes the nodes

The workload requests roughly 400 m of CPU in total, which a `t3.small` would carry easily. The cluster nevertheless runs `t3.large`, because with the AWS VPC CNI each pod consumes a real VPC IP address from an ENI attached to the node, and the number of ENIs and addresses per ENI is a property of the instance type.

Small instance types therefore run out of **addresses** long before they run out of CPU. Counting the system pods — CoreDNS, `kube-proxy`, the CNI, the EBS CSI controller — plus Traefik, cert-manager and five application pods, a `t3.small` does not fit.

The practical rule: on EKS with the default CNI, size nodes by pod count first and by CPU and memory second, and confirm the real limit from the cluster rather than from a table:

```bash
kubectl get node -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.allocatable.pods}{"\n"}{end}'
```

Prefix delegation on the CNI raises the limit substantially and is the usual answer when this becomes a cost problem. It is not configured here.

## A security gate only proves itself by rejecting something

A Trivy scan was added to CI with `exit-code: 1` on `CRITICAL` severity. The temptation with any new gate is to assume it works because the pipeline is green. It does not prove anything until it has actually stopped a bad build.

That happened in this project: the scan failed on the `result` and `worker` images, naming vulnerable versions of `express` and `StackExchange.Redis`, plus unpatched operating system packages in both base images. The fix was a dependency bump in each `package.json` and `.csproj`, and an `apt-get upgrade` added to both Dockerfiles so the layer itself is patched, not only the application dependency. Recorded as version 0.7.1.

The ordering matters as much as the gate itself: the workflow builds the image, scans it, and **only then** pushes it to the registry. A vulnerable image is therefore never published, rather than published and flagged after the fact. A scan that runs after publication is a report; a scan that runs before publication is a gate.

## Adopting a live system into GitOps, without breaking it

Argo CD was not pointed at the running application on day one. The live demonstration already existed and had to keep working throughout.

The sequence used: an isolated, disposable workload (`gitops-demo`, a single nginx Deployment) proved the installation and the sync mechanism first, with no risk to anything real. Only once that worked was the real `vote-dev-apps` Application created, pointed at the manifests that were already running in the cluster, so Argo CD's first sync **adopted** existing objects rather than creating new ones. Automatic sync and self-healing were enabled only after that adoption was confirmed not to have replaced anything.

Two settings did more safety work than any amount of care would have:

- **`prune: false`.** Argo CD will never delete a resource it does not recognise as declared in Git. The `postgres-credentials` Secret, created by hand and present in no manifest, is therefore never a deletion candidate — not because anyone remembered to exclude it, but because it was never tracked in the first place.
- **The `AppProject` resource whitelist.** Limiting the project to `Service` and `apps/Deployment` means a manifest for anything else — a Secret, a StatefulSet, a Namespace — cannot be synced even by mistake. The boundary is enforced by the API server, not by a reviewer's attention.

The resulting scope is deliberately narrow: Argo CD manages three Deployments and three Services. Routing, data services, cert-manager and Traefik are still applied by hand. Widening that scope is real future work, and the narrow boundary is itself the safety mechanism, not a shortcut that happened to work this time.

## Separating a code change from its deployment

A feature branch and a release branch are not the same pull request. `feature/vote-landing-page` changed the template and stylesheet; `release/vote-landing-page` changed one line in a Kubernetes manifest to point at the image that feature built. Both merged to `dev`, as two separate, independently revertible commits.

The payoff showed up directly: when a release needed to be rolled back, `git revert` on the release commit alone restored the previous image with no change to the application source, and the revert was itself reverted once the real fix landed. Mixing the two into one commit would have made a rollback an editing exercise instead of a single command.

## What must never be committed

| Never | Why |
|---|---|
| The `postgres-credentials` Secret, in any form | It is the only application credential. It is created manually and lives only in the cluster. |
| AWS access keys or secret keys | Nothing in this architecture needs one. Pod Identity and instance roles replace them entirely. |
| `kubeconfig` files | They embed cluster access. Generated on demand with `aws eks update-kubeconfig`. |
| Terraform state or `.tfstate` backups | State contains every resource attribute, and for some resource types that includes secrets. |
| Private keys, certificates, ACME account keys | cert-manager creates and stores these in the cluster. |
| `.env` files with real values | Only `app/.env.template`, which has keys and no values, is committed. |

Deliberately committed, and accepted as published for a portfolio repository: the AWS account ID `899088266068`, the Route 53 hosted zone ID, the VPC CIDR, subnet IDs in `values-public.yaml`, and the generated NLB hostname. None is a credential. The acceptance is written down in [architecture.md](architecture.md#committed-identifiers) rather than left implicit, because the original plan contained a rule against committing the account ID and that rule was not followed.

## Cost and the order in which things must be destroyed

The demonstration costs roughly 250 to 290 USD per month at list price, about 0.35 USD per hour, dominated by the EKS control plane, two On-Demand nodes and the NAT Gateway. Idle cost is nearly the whole cost: a cluster serving no traffic bills almost the same as a busy one.

Teardown order is counter-intuitive, and getting it wrong leaves resources billing after `terraform destroy` reports success:

1. **Delete the Traefik `Service` or Helm release first.** The NLB belongs to Kubernetes, not Terraform. `terraform destroy` will not remove it, and an orphaned NLB bills hourly forever.
2. **Delete the PVC explicitly and decide about the volume.** With `reclaimPolicy: Delete` the volume goes with the PVC and the data is gone. With `Retain` it survives and keeps billing. Either way it is a decision, not a default.
3. **Then destroy the Terraform roots in reverse dependency order** — `eks`, then `iam`, then `network` — because the `eks` root reads the other two through `terraform_remote_state`.
4. **Keep the `bootstrap` root.** It holds the state bucket, and it is protected by `prevent_destroy`.
5. **Verify afterwards.** The three resources most often left behind are a Kubernetes-created load balancer, an EBS volume kept by a `Retain` policy, and a NAT Gateway with its Elastic IP.

The full procedure, with the verification commands, is in [operations/teardown.md](operations/teardown.md).
