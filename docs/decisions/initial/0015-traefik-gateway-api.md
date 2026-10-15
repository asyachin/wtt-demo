# 0015 — Route With Traefik and the Gateway API

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | [0008](0008-ingress-and-dns.md) |
| Superseded by | none |

## Context

[ADR 0008](0008-ingress-and-dns.md) chose the AWS Load Balancer Controller with the `Ingress` API. That record considered three options, all of them Ingress-based. It did not consider the Gateway API at all, and it did not consider Traefik. That was an omission rather than a rejection, so the decision is re-opened here.

The state of the ecosystem as of this date, verified rather than remembered:

| Fact | Detail |
|---|---|
| Gateway API with AWS Load Balancer Controller | Generally available since controller v3.0.0, announced 6 March 2026. `HTTPRoute` over ALB needs v2.14.0 or later plus the `ALBGatewayAPI` feature gate. ACM certificates are discovered automatically by listener hostname. |
| Gateway API with Traefik | Traefik v3 implements the Standard channel. v3.7 and v3.8 target specification v1.6.x, with full `HTTPRoute` core support. |
| ALB limits under the Gateway API | `ListenerTLSConfig.certificateRefs` is not supported and must be replaced by the vendor CRD `LoadBalancerConfiguration`. `ResponseHeaderModifier`, `CORS`, and `ExternalAuth` filters are not supported. |
| ALB response headers | Supported since 2024, but through listener attributes such as `routing.http.response.strict_transport_security.header_value`, not through any Kubernetes API. |

Two project goals bear directly on this. The stated aim includes separation of responsibility, and the README claims the operational patterns apply to a private cloud platform.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| Keep ALB with the `Ingress` API | Fewest components. Nothing new to run. The simplest and most reliable path. | No Gateway API in the project. Separation of responsibility stays a claim rather than an object. Routing cannot be tested without AWS. |
| ALB with the Gateway API | No new runtime component. ACM stays. Gains the role model and cross-namespace routing. | TLS only through a vendor CRD, which undercuts the portability argument for adopting a standard API. Still nothing to test in `kind`. Behind two feature gates. |
| Traefik with the Gateway API | Routing is testable in `kind`. Fully portable. The role model is real. Native response-header and authentication filters. | One more component in the traffic path, to patch, monitor, scale, and recover. TLS becomes the project's problem. |
| Traefik with its own `IngressRoute` CRDs | Easier to debug, richer middleware | A vendor API instead of a standard one, which loses the portability that is the main reason to pick Traefik |

## Decision

Traefik v3 is the gateway implementation, configured through the Gateway API.

| Object | Owner | Where |
|---|---|---|
| `GatewayClass` named `traefik`, controller `traefik.io/gateway-controller` | Platform, installed by Terraform | cluster-scoped |
| `Gateway` named `wtt-demo`, listeners on 8000 for HTTP and 8443 for HTTPS, `allowedRoutes.namespaces` restricted by label selector | Platform, installed by Terraform | namespace `traefik` |
| `HTTPRoute` for `vote` and `result` | Application, in the Helm chart | namespaces `vote-dev` and `vote-prod` |
| `HTTPRoute` for Grafana | Observability, in the observability application | namespace `observability` |
| `ReferenceGrant` where a route points at a Service in another namespace | Application | the backend's namespace |

Traefik is exposed by a Service of type `LoadBalancer`, which the in-tree AWS cloud provider realises as a Network Load Balancer in L4 mode. Traefik terminates TLS itself, with certificates from cert-manager; see [0016](0016-tls-with-cert-manager.md).

The Standard channel CRDs only. `providers.kubernetesGateway.experimentalChannel` is explicitly set to `false`.

The AWS Load Balancer Controller is not installed. ExternalDNS stays, with its source changed from `ingress` to `gateway-httproute`.

## Reasoning

### Testability is the deciding argument

Under ADR 0008, the entire routing layer was first exercised on live AWS in Block 07. Block 05 could only check that a manifest rendered and matched a schema, because an ALB does not exist in `kind`. That meant the first real test of path matching, of the `/result/socket.io` websocket, and of the HTTP to HTTPS redirect happened on a cloud resource, by hand, with a 180 second feedback loop.

Traefik behaves identically in `kind` and on EKS, because it is the same pod reading the same `HTTPRoute`. Four tests move from "run by hand against AWS" to "run in CI on every push", and the feedback loop for a routing change goes from minutes to seconds. For a project where most of the plan's tests already cannot run in CI, moving four of them back is worth a component.

### The Gateway API is the right API regardless of implementation

Separation of responsibility was listed as a goal. Under `Ingress` it is one object owned by nobody in particular, and every real-world refinement is a vendor annotation. Under the Gateway API it is three objects with three owners: the platform owns the `GatewayClass` and the `Gateway` and decides which namespaces may attach, and the application owns its `HTTPRoute`. `allowedRoutes` and `ReferenceGrant` make the boundary enforceable by the API server rather than by convention. That is a demonstrable artefact, which is what this project is for.

### Why not ALB with the Gateway API

This was the close contender, and it loses on one point. The main reason to adopt a standard API is that the manifests stop being vendor-specific. On ALB, the one thing a `Gateway` listener cannot express is its own TLS configuration: `certificateRefs` is unsupported and the work moves into `LoadBalancerConfiguration`, an AWS CRD. The response-header and authentication filters are unsupported too. So the manifests would carry the Gateway API's shape while the parts that matter stayed AWS-only, which buys the vocabulary without the portability. If the choice is to pay nothing and gain the role model, that option is good; if the claim is portability, it does not hold.

### The honest cost

Traefik sits in the path of every public request. It needs resource limits, a PodDisruptionBudget, two replicas, an alert, a dashboard, a patching routine, and a runbook section. None of that existed with a managed ALB.

Three implementation traps are known in advance and are written into the plan rather than discovered:

- **The redirect loop.** The NLB in L4 mode forwards TCP and adds no `X-Forwarded-Proto`. A single Traefik entrypoint cannot tell an HTTP request from an HTTPS one, so a redirect rule applies to both and loops. The fix is two entrypoints, 8000 and 8443, with the redirect configured only on 8000, and NLB listeners mapped one to one.
- **Client IP addresses.** In L4 mode Traefik sees NLB addresses, not client addresses, unless Proxy Protocol v2 is enabled on the target group and on the Traefik entrypoint. Both sides have to be enabled together; enabling one alone breaks all traffic.
- **The experimental channel.** Setting `experimentalChannel: true` without the Experimental CRDs installed makes the whole Gateway provider fail to serve any resource, so unrelated and previously working `HTTPRoute` objects start returning 404. This project needs only the Standard channel, so the option stays `false` and a test asserts it.

### Decisions re-opened and left standing

[ADR 0009](0009-observability.md) argued in part that Prometheus could not easily be published because the ALB has no basic authentication. Traefik does have it, so that specific argument no longer applies. The decision was re-examined and stands unchanged, on its remaining and stronger grounds: one public component instead of two, scoped and revocable tokens instead of a shared password, and no second endpoint to secure. Basic authentication would be a step backwards even though it is now available. ADR 0009 is not edited, per [0001](0001-record-architecture-decisions.md).

[ADR 0005](0005-gitops-with-argocd.md) listed the AWS Load Balancer Controller among the components Terraform owns. The boundary rule it defines is unchanged: Traefik and cert-manager take that slot, because a cluster with no gateway cannot serve a route and bootstrapping that through Argo CD would create a dependency loop.

Three other records contain details that this decision and [0016](0016-tls-with-cert-manager.md) make stale. None of their decisions changes, so none is superseded and none is edited:

| Record | Stale detail | Still correct |
|---|---|---|
| [0003](0003-single-cluster-two-namespaces.md) | Refers to one ALB listener, and to `kind` not exercising the ALB | One cluster with two namespaces, and development with no public hostname. The `kind` argument is now weaker, because Traefik does make routing testable there, but the AWS-specific parts it names, IRSA and EBS, still are not. |
| [0009](0009-observability.md) | Argues in part that the ALB cannot do basic authentication | Publish Grafana only and reach Prometheus through its data source proxy, for the reasons above |
| [0014](0014-domain-and-dns-zone.md) | Refers to an ACM certificate | The hostname, the hosted zone, the wildcard scope, and the reasoning for all three |

## Consequences

### Positive

- The routing layer is tested in CI, in `kind`, on every push.
- The manifests are standard Gateway API and carry no vendor annotation, so they move to any conformant implementation.
- Separation of responsibility is enforced by `allowedRoutes` and `ReferenceGrant` rather than by convention.
- Response headers, redirects, and authentication are expressed in Kubernetes objects, not in load balancer listener attributes outside the cluster.
- The NLB is created by a `Service`, so `kubectl delete` of the Traefik release removes it, which is harder to orphan than an ALB created from an `Ingress`.
- The same configuration runs on a laptop, in `kind`, and on EKS.

### Negative

- Traefik is a new single point of failure in the public traffic path. Two replicas across two nodes and a PodDisruptionBudget bound it, but on a two-node cluster that means both nodes carry a Traefik pod.
- Terminating TLS in the cluster means the certificate is the project's problem. That cost is accounted for separately in [0016](0016-tls-with-cert-manager.md), and it is the single largest consequence of this decision.
- The three traps above are real and two of them produce confusing symptoms: a redirect loop, and missing client addresses in logs.
- AWS WAF and ALB access logs are no longer available, because there is no ALB. Neither is used today, and regaining them would mean putting an ALB in front of the NLB.
- Gateway API CRDs are cluster-scoped and must be installed and version-pinned before Traefik starts. A CRD version mismatch is a cluster-wide failure, not a namespace one.
- Traefik's own metrics, dashboard, alert, and runbook section are additional work in Blocks 10 and 13.
- ADR 0008 is superseded two hours after it was written, which is an honest record of having missed an option rather than something to hide.

### Neutral

- An NLB costs about the same as an ALB, so there is no cost change.
- ExternalDNS changes its source flag from `ingress` to `gateway-httproute`. Its IAM scope is unchanged.
- The routing rules themselves are unchanged from ADR 0008: `/` to `vote`, `/result` as a prefix to `result` so that `/result/socket.io` is covered, and Grafana on its own hostname.

## Verification

Block 05, in `kind`, in CI:

- `test_gateway_is_accepted` — the `Gateway` reports `Accepted` and `Programmed`
- `test_httproute_is_attached` — every `HTTPRoute` reports a resolved parent reference
- `test_routing_matches_paths` — `/` reaches `vote` and `/result` reaches `result`
- `test_websocket_upgrade_succeeds` — a websocket handshake on `/result/socket.io` returns 101
- `test_http_redirects_to_https_in_kind` — the redirect filter on the HTTP listener answers 301
- `test_experimental_channel_disabled` — the Traefik values set `experimentalChannel: false`
- `test_allowed_routes_restricts_namespaces` — an `HTTPRoute` in an unlabelled namespace is rejected with `NotAllowedByListeners`

Block 07, against EKS:

- `test_traefik_is_running`, `test_nlb_is_provisioned`, `test_proxy_protocol_passes_client_ip`
- `test_externaldns_creates_record_from_httproute`

Block 12:

- `test_security_headers_present`, now satisfied by a `ResponseHeaderModifier` filter on the route rather than by a load balancer attribute
- `test_prod_route_cannot_attach_to_dev_listener`

## Revisit When

AWS WAF or ALB access logs become a requirement, or the operational cost of running Traefik outweighs the testability gain. Either one points back to ALB, and by then the Gateway API manifests would move across with only the TLS configuration changing.
