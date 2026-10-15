# 0007 — Two Secret Stores, With a Sharp Boundary

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | none |

## Context

The project needs credentials in two places that have nothing to do with each other.

CI needs database credentials so that the `integration` job can start a PostgreSQL container, run tests against it, and throw it away. Those credentials exist for the duration of one job.

Running environments need a real PostgreSQL password, a Grafana admin password, an Argo CD admin password, and a read-only Grafana API token. Those exist until they are rotated.

The starting position is bad. `app/docker-compose.deploy.yml` has `postgres/postgres` in plain text, `app/.env` is a symlink to another project's secret file, and `app/.env.template` ships default credentials. The author has asked for the development values to be loaded into GitHub so that the tests can run.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| GitHub Actions secrets for CI, AWS Secrets Manager for environments | Each store holds only what it needs. A GitHub compromise does not expose a running environment. | Two systems to understand. Two rotation procedures. |
| Everything in GitHub Actions secrets | One place | CI would need to inject secrets into the cluster, which means CI needs cluster credentials, which contradicts [0005](0005-gitops-with-argocd.md). A GitHub compromise exposes production. |
| Everything in AWS Secrets Manager | One place, strongest store | The CI `integration` job would need an AWS role just to get a throwaway password for a container that lives two minutes |
| Sealed Secrets or SOPS in Git | No external store, secrets versioned with the code | An encrypted secret in Git is still a secret in Git, and the decryption key becomes the thing to protect. Rotation means a commit. |
| HashiCorp Vault | The most capable | Far too much for four secrets, and it would become the most complex component in the system |

## Decision

Two stores, with a boundary that is defined by lifetime:

| Store | Holds | Lifetime |
|---|---|---|
| GitHub Actions environment `dev` | Credentials for containers that exist inside one pipeline job | One job |
| AWS Secrets Manager, prefix `/wtt-demo/` | Everything a running environment uses | Until rotated |

Secrets reach pods through the External Secrets Operator, which reads Secrets Manager using an IRSA role scoped to `secretsmanager:GetSecretValue` on `arn:...:secret:/wtt-demo/*`, and writes a Kubernetes Secret. Workloads reference it with `secretKeyRef` and never with a literal value.

AWS credentials themselves are never stored. GitHub Actions authenticates to AWS with OpenID Connect. Workloads authenticate with IRSA. There is no long-lived access key in this project.

## Reasoning

The boundary is drawn by lifetime rather than by sensitivity, because lifetime is objective. A value that a container uses for two minutes and then discards is in a different class from a value that guards production data for a month, and the two should not share a store.

The practical consequence is the one that matters: a compromise of the GitHub account does not expose a running environment. GitHub holds nothing that outlives a job. That is only true because the boundary is enforced, and it is the reason the author's request to put the development values into GitHub is safe to grant.

SOPS and Sealed Secrets were rejected because they solve the wrong problem here. They exist to put secrets in Git safely, and the goal is to have no secrets in Git at all. They would also move rotation into the commit path, which makes an urgent rotation slower.

Vault was rejected on size. Four secrets do not justify a service that would need its own high availability, its own unsealing procedure, and its own backup.

The absence of any long-lived AWS key is the strongest single security property of the design, and it comes free from OpenID Connect and IRSA. It is worth stating plainly because it is the kind of thing a reviewer looks for.

## Consequences

### Positive

- No secret in Git, in a Helm value, in a Terraform variable file, or in an image. Enforced by `gitleaks` on the full history and by three unit tests.
- No long-lived AWS access key anywhere.
- A GitHub compromise cannot reach a running environment.
- Rotation is a single API call plus a rollout, and AWS keeps previous versions so a bad rotation can be undone.
- The backup job has no credential at all, because IRSA replaces it.

### Negative

- Two stores means two rotation procedures and two places to look. Both are written down in `docs/ops/secrets.md`.
- A Kubernetes Secret is base64, not encryption. Anyone with `get secret` in the namespace reads the value in clear text. RBAC in Block 12 limits that, and the control plane audit log records it, but the underlying weakness remains.
- The External Secrets Operator is another component in the critical path. If it fails, a new pod cannot get its secret, although existing pods keep running.
- The refresh interval is one hour, so a rotation is not instant unless a force-sync annotation is applied.
- Rotating the PostgreSQL password needs two steps that must both happen: the value in Secrets Manager and the password inside PostgreSQL. Doing only the first produces a failure that looks like a network problem. This trap is called out in the procedure.

### Neutral

- Secrets Manager costs about 0.40 USD per secret per month. For five secrets this is negligible and is in the cost table.
- The Terraform resources that create the secrets use `ignore_changes` on the value, so a rotation is not reverted by the next apply. Without that, every apply would silently restore the original generated password.

## Verification

- `gitleaks detect` over the full history, in CI, on every push.
- `test_no_secret_literal_in_helm_values` and `test_no_secret_in_terraform_tfvars` in Block 09.
- `test_all_secret_env_vars_use_secret_key_ref` in Block 09.
- `test_rotation_propagates` in Block 09, which rotates for real and confirms the application still works.
- `test_irsa_is_scoped` in Block 09, which confirms a read outside `/wtt-demo/*` is denied.
- `test_password_not_in_pod_logs` in Block 09, and `test_no_password_in_any_log` in Block 02.

## Revisit When

A second person needs access, which makes an audit trail per human necessary and justifies looking at Vault or AWS IAM Identity Center. Or the one-hour refresh interval becomes too slow, which is a configuration change rather than a new decision.
