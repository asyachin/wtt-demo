# Secrets

## Rule

A secret has exactly one home. Everything else holds a reference to it.

No secret exists in Git, in a Helm value file, in a Terraform variable file, in a container image, or in a log line. This is enforced by tests, not by discipline: `gitleaks` on the full history, `test_no_secret_literal_in_helm_values`, `test_no_secrets_in_terraform_tfvars`, and `test_password_not_in_pod_logs`.

## Two Homes, One Boundary

| Home | Holds | Lifetime | Who can read it |
|---|---|---|---|
| GitHub Actions environment `dev` | Credentials for throwaway containers in a pipeline run | The length of one job | A workflow in this repository, in the `dev` environment |
| AWS Secrets Manager, prefix `/wtt-demo/` | Everything a running environment uses | Until rotated | An IRSA role scoped to that prefix, and the repository owner |

The boundary is deliberate. A compromise of the GitHub account must not expose a running environment. GitHub therefore holds nothing that outlives a pipeline run: the PostgreSQL password in the `dev` environment belongs to a container that is created and destroyed inside a single `integration` job. The full reasoning is in [ADR 0007](../adr/0007-secrets-management.md).

AWS credentials are the one thing that is never stored anywhere. GitHub Actions authenticates to AWS with OpenID Connect, and workloads in the cluster authenticate with IRSA. There is no long-lived access key in this project.

## The Secret Map

| Secret | Home | Path or name | Reaches a pod by | Rotation |
|---|---|---|---|---|
| PostgreSQL password, production | AWS Secrets Manager | `/wtt-demo/prod/postgres` | `ExternalSecret` into Secret `postgres-credentials` in `vote-prod` | Manual, see below |
| PostgreSQL password, development | AWS Secrets Manager | `/wtt-demo/dev/postgres` | The same, in `vote-dev` | Manual |
| Grafana admin password | AWS Secrets Manager | `/wtt-demo/prod/grafana` | `ExternalSecret` into `observability` | Manual |
| Grafana read-only API token | AWS Secrets Manager | `/wtt-demo/prod/grafana-reader` | Created once in Grafana, stored here, handed to reviewers | Revoke in Grafana, create a new one, update the secret |
| Argo CD admin password | AWS Secrets Manager | `/wtt-demo/prod/argocd` | Read by Terraform at install time | Manual |
| Backup bucket access | none | not applicable | IRSA role on the backup service account. There is no credential. | not applicable |
| GHCR pull access | none | not applicable | The packages are public. There is no pull secret. | not applicable |
| AWS access for CI | none | not applicable | OpenID Connect, a role assumed per job | not applicable |
| Test database credentials | GitHub Actions environment `dev` | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Environment variables in the `integration` job only | Replace the values when they change |

## How a Secret Reaches a Pod

```
AWS Secrets Manager
  /wtt-demo/prod/postgres   {"username": "...", "password": "..."}
        │
        │  read by the External Secrets Operator,
        │  using an IRSA role limited to secretsmanager:GetSecretValue on /wtt-demo/*
        ▼
ClusterSecretStore  aws-secrets-manager
        │
        │  an ExternalSecret in the namespace names the path and the keys
        ▼
Kubernetes Secret  postgres-credentials  in namespace vote-prod
        │
        │  referenced by secretKeyRef, never by a literal value
        ▼
Pod environment:  PG_PASSWORD, DB_PASSWORD, POSTGRES_PASSWORD
```

The refresh interval is 1 hour. A rotation is therefore visible in the cluster within an hour, and immediately if the `ExternalSecret` is annotated to force a refresh.

A Kubernetes Secret is base64, not encryption. Anyone with `get secret` in the namespace can read the value. That is why RBAC in Block 12 grants `get secret` to nobody except the service accounts that need it, and why the audit log on the control plane is enabled in Block 06.

## Rotating the PostgreSQL Password

Roughly 10 minutes, with a short interruption while the pods restart. The measured duration is recorded when this procedure is first run in Block 09.

```
# 1. Generate a new value and write it into Secrets Manager
NEW=$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)
aws secretsmanager put-secret-value \
  --region eu-north-1 \
  --secret-id /wtt-demo/prod/postgres \
  --secret-string "{\"username\":\"voteapp\",\"password\":\"$NEW\"}"

# 2. Change the password inside PostgreSQL itself
kubectl -n vote-prod exec -it postgres-0 -- \
  psql -U postgres -c "ALTER USER voteapp WITH PASSWORD '$NEW'"

# 3. Force the External Secrets Operator to refresh now instead of waiting an hour
kubectl -n vote-prod annotate externalsecret postgres-credentials \
  force-sync="$(date +%s)" --overwrite

# 4. Confirm the Kubernetes Secret has the new value
kubectl -n vote-prod get secret postgres-credentials \
  -o jsonpath='{.data.password}' | base64 -d

# 5. Restart the consumers so they pick it up
kubectl -n vote-prod rollout restart deployment/result deployment/worker
kubectl -n vote-prod rollout status deployment/result --timeout=120s

# 6. Verify
curl -sf https://wtt-demo.syachin.de/result > /dev/null && echo ok
kubectl -n vote-prod logs deployment/worker --tail=20
```

Step 2 is the one that is easy to forget. Changing the secret without changing the database leaves the application unable to connect, and the symptom looks like a network problem.

The `ignore_changes` lifecycle rule on the Terraform secret resource means a later `terraform apply` will not overwrite the rotated value. Without it, the next apply would silently restore the original generated password.

### Rolling Back a Rotation

AWS Secrets Manager keeps previous versions. If the new password breaks something:

```
aws secretsmanager list-secret-version-ids --secret-id /wtt-demo/prod/postgres
aws secretsmanager update-secret-version-stage \
  --secret-id /wtt-demo/prod/postgres \
  --version-stage AWSCURRENT \
  --move-to-version-id <previous version id> \
  --remove-from-version-id <current version id>
```

Then run steps 2 to 6 again with the previous value.

## Rotating the Grafana Read-Only Token

```
# 1. Revoke the old token in Grafana, under Administration, Service accounts
# 2. Create a new token on the same service account, with the Viewer role only
# 3. Store it
aws secretsmanager put-secret-value \
  --region eu-north-1 \
  --secret-id /wtt-demo/prod/grafana-reader \
  --secret-string '{"token":"<new token>"}'

# 4. Confirm it can read and cannot write
curl -sf -H "Authorization: Bearer <new token>" \
  'https://grafana.wtt-demo.syachin.de/api/datasources/proxy/uid/prometheus/api/v1/query?query=up' \
  | jq '.status'                      # expect "success"

curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H "Authorization: Bearer <new token>" \
  -H 'Content-Type: application/json' \
  -d '{"dashboard":{"title":"should not be created"}}' \
  https://grafana.wtt-demo.syachin.de/api/dashboards/db
                                      # expect 403
```

The second check matters. A token given to a reviewer must not be able to change anything. `test_grafana_token_cannot_write` in Block 10 makes this permanent.

## Recovering the Argo CD Admin Password

```
aws secretsmanager get-secret-value \
  --region eu-north-1 --secret-id /wtt-demo/prod/argocd \
  --query SecretString --output text | jq -r .password

kubectl -n argocd port-forward svc/argocd-server 8443:443
argocd login localhost:8443 --username admin --insecure
```

If the secret is lost, the password can be reset by deleting the `argocd-secret` key and restarting the server, which is described in the Argo CD recovery section of [runbooks.md](runbooks.md).

## If a Secret Leaks

Order matters. Rotation comes first, every time.

1. **Rotate the value.** Do this before anything else. A value that reached a commit, a log, a screenshot, or a chat message is compromised, whether or not the commit was pushed and whether or not the history is rewritten.
2. Work out the exposure window: when the value was created, when it leaked, and when it was rotated.
3. Check the CloudTrail and the control plane audit log for use of the value during that window.
4. Remove the value from where it leaked. For Git, prefer starting a clean history over a rewrite, because a rewrite leaves copies in forks, caches, and pull request views.
5. Write down what happened and which test would have caught it. If no test would have, add one.

## Verifying the Whole Chain

Run after any change to secret handling.

```
gitleaks detect --source . --redact
pytest tests/unit/test_no_secrets_in_repo.py
pytest -m platform tests/platform/test_secrets_delivery.py

# No password anywhere in the pod logs
for d in vote result worker; do
  kubectl -n vote-prod logs deployment/$d --tail=500
done | grep -c "$(aws secretsmanager get-secret-value \
  --region eu-north-1 --secret-id /wtt-demo/prod/postgres \
  --query SecretString --output text | jq -r .password)"
# expect 0
```
