# 0003 — One EKS Cluster With Two Namespaces

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | none |

## Context

The project needs a development environment and a production environment. Production is publicly reachable at `wtt-demo.syachin.de` and must stay up for the length of an interview process. Development is where a change is proven before it is promoted.

An EKS control plane costs about 72 USD per month regardless of what runs on it. The whole demonstration has a budget of roughly 145 USD per month.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| One cluster, two namespaces | Half the control plane cost. One `terraform apply`. Namespace isolation has to be done properly, which is itself worth demonstrating. | A cluster-wide failure or a bad upgrade affects both environments. Namespace isolation is weaker than cluster isolation. |
| Two clusters | Full isolation, which is the correct answer for real production | Twice the control plane cost, twice the apply time, twice the add-on configuration, two kubeconfigs |
| Development in local `kind`, production in EKS | Cheapest. Fast feedback. | Development does not exercise the ALB, IRSA, EBS, or ACM, which is where real problems live. A change proven in `kind` is not proven. |

## Decision

One EKS cluster named `wtt-demo`, with the application in two namespaces: `vote-dev` and `vote-prod`. Each namespace is an Argo CD Application tracking a different branch. The namespaces are isolated by a default-deny `NetworkPolicy`, a `ResourceQuota`, a `LimitRange`, and separate service accounts and secret paths.

Development is not published to the internet. It is reached with `kubectl port-forward`.

## Reasoning

The cost argument decides it. Seventy-two dollars a month for a second control plane buys isolation that a demonstration does not need, and the same money is better spent on keeping the environment running longer.

The weaker isolation is turned into an advantage. Doing namespace separation properly, with default-deny networking, quotas, and a test that proves a production pod cannot reach a development service, demonstrates more skill than provisioning two clusters does. `test_prod_cannot_reach_dev` in Block 12 is the evidence.

`kind` for development was rejected because the things that break in this architecture are the AWS integrations: a missing subnet tag, an IRSA trust policy with the wrong service account, an EBS volume in the wrong availability zone. None of them appear in `kind`. A development environment that cannot reproduce the production failure modes is not a development environment. `kind` is still used, but for what it is good at: fast Helm chart validation in CI, in Block 05.

The deliberate asymmetry is that development has no public hostname. That keeps one certificate, one ALB listener, and one public surface to secure, and nothing in the development workflow needs a public address.

## Consequences

### Positive

- About 72 USD per month saved.
- One Terraform root module, one set of add-ons, one kubeconfig.
- Namespace isolation is implemented and tested rather than assumed.

### Negative

- A cluster upgrade affects both environments at once, so there is no way to prove an upgrade in development first. This is accepted: the cluster version is pinned and is not upgraded during the interview process.
- A noisy pod in `vote-dev` can affect `vote-prod` through node resources. The `ResourceQuota` and `LimitRange` bound it, and `vote-dev` is given the smaller quota.
- Cluster-scoped objects such as CustomResourceDefinitions and the Argo CD installation are shared. A mistake there affects both environments.
- Development cannot be tested over a real HTTPS path, because it has no public hostname. The end-to-end suite therefore runs against production, after promotion, which means production is where a TLS problem is first seen.

### Neutral

- Both namespaces appear in the same `kubectl get pods -A` output, which is convenient and also a way to confuse the two. Every command in the runbooks names its namespace explicitly.

## Verification

- `test_prod_cannot_reach_dev` in Block 12.
- `test_quotas_defined_for_both_namespaces` in Block 12.
- `test_dev_and_prod_differ_only_in_allowed_keys` in Block 05, which fails if the two environments drift beyond the permitted keys.

## Revisit When

The platform has to serve someone other than its author, or a cluster upgrade has to be proven before it reaches production. Either one justifies a second cluster.
