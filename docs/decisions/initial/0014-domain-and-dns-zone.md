# 0014 — Use wtt-demo.syachin.de

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | none |

## Context

The repository contained two different public addresses.

`README.md` advertised `https://wtt-campusone.click` in three places, including the footer. That domain is not registered to this project and there is no hosted zone for it.

A scratch file, `ns.tmp`, held a copy of the Route 53 record set for `syachin.de`, with its four name servers and its start-of-authority record, and the line `https://wtt-demo.syachin.de`.

So the README pointed at a domain that does not resolve, and the working notes pointed at a domain that does. A public address on a job application that returns nothing is worse than having no address at all.

There is a further consideration. The name `wtt-campusone.click` reads as if it belongs to WTT CampusONE. It does not. The company's real domain is `wtt-campusone.com`, and a near-identical name on a different top-level domain, hosting something the company did not build, is the shape of a phishing domain. Even with a disclaimer, it is a bad choice.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| `wtt-demo.syachin.de` under the existing zone | The zone exists, so no registration and no name server delegation. The name is clearly the author's own and clearly a demonstration. A wildcard certificate covers the subdomains. | Nothing significant |
| `wtt-campusone.click` | Matches what the README already said | Not registered. Needs a new zone and delegation. Impersonates the company's name on a different top-level domain. |
| Two names, one per environment | Development reachable over real HTTPS | A second public surface, a second certificate, and a development environment exposed to the internet for no benefit. Contradicts [0003](0003-single-cluster-two-namespaces.md). |
| An AWS-generated load balancer hostname | Nothing to configure | Unreadable, no TLS certificate for a custom name, and it changes if the load balancer is recreated |

## Decision

The canonical public address is `https://wtt-demo.syachin.de`.

| Name | Serves |
|---|---|
| `wtt-demo.syachin.de` | The voting page at `/` and the result page at `/result` |
| `grafana.wtt-demo.syachin.de` | Grafana, including the metrics HTTP API |

The hosted zone `syachin.de` already exists in Route 53 and is referenced by Terraform as a data source, not created by it. The ACM certificate covers `wtt-demo.syachin.de` and `*.wtt-demo.syachin.de`. Records are written by ExternalDNS, scoped by IAM to that one zone.

Every reference to `wtt-campusone.click` is removed from the repository, and a test keeps it removed. `ns.tmp` is deleted; the name server details belong in the Route 53 console, not in a scratch file in a repository.

The development namespace gets no public name. It is reached with `kubectl port-forward`.

## Reasoning

The zone already exists, which removes domain registration and name server delegation from the critical path. Delegation can take up to 48 hours to propagate, and that is not a delay worth taking for a cosmetic name.

The naming is honest. `wtt-demo.syachin.de` is plainly a demonstration on the author's own domain. `wtt-campusone.click` would read as the company's own site, which is misleading at best. For a project whose purpose is to demonstrate judgement, choosing a name that could be mistaken for impersonating the employer is a poor first impression, and no README disclaimer repairs it.

The subdomain layout is deliberate. Putting Grafana under `wtt-demo.syachin.de` rather than directly under `syachin.de` keeps everything for this project inside one label, so the whole demonstration is covered by one wildcard certificate and can be removed by deleting one subtree. It also keeps the author's personal domain uncluttered if other projects follow.

A wildcard covering `*.wtt-demo.syachin.de` means a new component needs no certificate work. Adding `argocd.wtt-demo.syachin.de` later, if that decision were reversed, would need only an ingress rule.

## Consequences

### Positive

- No domain registration and no delegation delay.
- One certificate covers the current names and any future subdomain.
- The name cannot be mistaken for the company's own site.
- The whole demonstration lives under one DNS label and can be removed as a unit.
- The README now points at an address that resolves.

### Negative

- The address is tied to a personal domain, so the demonstration depends on that registration staying active.
- Every document, test, and Helm value that contains the hostname has to be changed if the name ever changes. The hostname appears in the Helm values, the Terraform variables, the end-to-end test defaults, and several documents. That is accepted because the name is not expected to change.
- The wildcard covers one label only, so `a.b.wtt-demo.syachin.de` is not covered. Nothing needs it.
- `syachin.de` is a shared zone. A mistake by ExternalDNS could in principle affect an unrelated record, which is why its IAM role is scoped to that single hosted zone and its record ownership is tracked by a registry TXT record.

### Neutral

- The README already carried a disclaimer that the project is not an official WTT CampusONE product. It stays, and with this name it is a courtesy rather than a necessity.

## Verification

- `test_no_previous_project_references` in Block 00 fails on any occurrence of `wtt-campusone.click`.
- `test_readme_links_are_reachable` in Block 13 requires every `https://` link in the README to return a successful status.
- `test_sample_ingress_creates_a_dns_record` and `test_sample_ingress_serves_valid_tls` in Block 07.
- `test_external_dns_scoped_to_one_zone` in Block 07.
- `test_certificate_is_issued` in Block 07 confirms the certificate covers both names.
- `dig +short wtt-demo.syachin.de` resolves to the load balancer.

## Revisit When

The project is handed over, or the personal domain is given up. Either one means a new zone and a superseding record.
