# Verify and troubleshoot

Section 1 needs nothing but a shell and the internet, and is the gate referenced by every block's Definition of Done. Later sections need cluster or AWS access.

Results marked **verified 15 Oct 2026** were run from a workstation outside AWS and are reproducible by any reader.

---

# 1. Public service

```bash
HOST=wtt-demo.syachin.de

dig +short $HOST

curl -sS -o /dev/null -w 'http  /          %{http_code} %{redirect_url}\n' http://$HOST/
curl -sS -o /dev/null -w 'https /          %{http_code}\n' https://$HOST/
curl -sS -o /dev/null -w 'https /result    %{http_code} %{redirect_url}\n' https://$HOST/result
curl -sS -o /dev/null -w 'https /result/   %{http_code}\n' https://$HOST/result/
curl -sS -o /dev/null -w 'https result js  %{http_code}\n' https://$HOST/result/app.js
curl -sS -o /dev/null -w 'socket.io        %{http_code}\n' \
  "https://$HOST/result/socket.io/?EIO=4&transport=polling"
```

Expected, and verified 15 Oct 2026:

```
dig                13.61.87.220, 13.60.127.160
http  /            301  https://wtt-demo.syachin.de:443/
https /            200
https /result      301  https://wtt-demo.syachin.de/result/
https /result/     200
https result js    200
socket.io          200
```

The HTTP redirect preserves path and query:

```bash
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' 'http://$HOST/result/?x=1'
# 301 https://wtt-demo.syachin.de:443/result/?x=1
```

The explicit `:443` comes from `port: 443` in the redirect route. Functionally correct, cosmetically untidy.

### Certificate

```bash
echo | openssl s_client -connect $HOST:443 -servername $HOST 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

Verified 15 Oct 2026: `CN = wtt-demo.syachin.de`, issuer `C = US, O = Let's Encrypt, CN = YR2`, valid 14 Oct 2026 to 12 Jan 2027, one SAN entry.

The issuer must name Let's Encrypt and **not** a staging authority. A staging certificate produces a browser warning while every `curl` above still passes, because `curl` reports the handshake separately from the trust decision.

### No external asset dependency

```bash
for path in / /result/; do
  echo "== $path"
  curl -sS "https://$HOST$path" | grep -oE '(src|href)="[^"]+"' | sort -u
done
```

Verified 15 Oct 2026: every reference is relative. **No `http://`, no `https://` to a third party, no protocol-relative `//host` form.** Both pages are fully self-hosted since v0.8.0, so there is nothing a browser can block and no CDN outage can affect them.

### Known-failing checks

Expected to fail today, listed so their absence is not read as success. [Block 04](../roadmap.md#block-04--what-remains) owns them.

```bash
curl -sSI https://$HOST/ | grep -iE 'strict-transport|x-frame|x-content|referrer-policy'
curl -sSI https://$HOST/ | grep -i '^server:'
```

Verified 15 Oct 2026: no security header is present, and `server: gunicorn` is disclosed.

---

# 2. Browser

**Cannot be scripted, and cannot be skipped.** Two defects in this project returned HTTP 200 for their entire lifetime: `/result` broke relative asset resolution, and the vote page's jQuery was blocked as mixed content. Section 1 passed throughout both.

| # | Check | Expected |
|---|---|---|
| 1 | Open `https://wtt-demo.syachin.de/` with DevTools Console and Network visible | Zero console errors. Zero failed or blocked requests. No request leaves the origin. |
| 2 | Submit a vote | **On the POST response** the chosen option is marked selected and a confirmation appears |
| 3 | Reload after voting | The highlight is **gone**. Correct: `vote` is set only on POST. Not a defect. |
| 4 | Open `/result/` in a second tab, vote in the first | The count changes with no manual reload |
| 5 | Network tab on the result page | A Socket.IO connection to `/result/socket.io/` established, not retrying |
| 6 | Resize to a phone width | Both pages remain usable |
| 7 | Address bar | Padlock present, no mixed-content indicator |

**Last recorded:** operator-verified in Chrome, 15 October 2026; browser version not recorded. Clean console, voted state on the POST response, live result updates observed.

---

# 3. Cluster

```bash
aws eks update-kubeconfig --region eu-north-1 --name wtt-demo-eks
```

Not run when this document was written — no AWS credentials were available in that session. Everything below needs operator verification.

### Workloads

```bash
kubectl get nodes -o wide
kubectl get node -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.allocatable.pods}{"\n"}{end}'
kubectl -n vote-dev get pods -o wide
kubectl -n traefik get pods
kubectl -n cert-manager get pods
kubectl -n argocd get pods
```

Expect two `Ready` nodes with no external address, and five pods in `vote-dev`. Restart counts should be low and stable; a climbing count means a crash loop. One replica each, so any restart is a brief outage.

The second command reports the real pod ceiling per node, which is what drove the `t3.large` choice.

### Storage

```bash
kubectl -n vote-dev get pvc
PV=$(kubectl -n vote-dev get pvc data-postgres-0 -o jsonpath='{.spec.volumeName}')
kubectl get pv "$PV" -o custom-columns=\
'NAME:.metadata.name,SIZE:.spec.capacity.storage,RECLAIM:.spec.persistentVolumeReclaimPolicy,EBS:.spec.csi.volumeHandle'
```

Expect a bound 5 GiB claim. **Expect `RECLAIM` to read `Delete`** — that is the data-loss risk owned by [Block 06](../roadmap.md#next-block).

### Gateway and routes

```bash
kubectl -n traefik get gateway traefik-gateway -o wide
kubectl get httproute -A
kubectl -n vote-dev describe httproute result | tail -25
```

Expect `PROGRAMMED: True` and four routes in `vote-dev`. Each should report `Accepted: True` and `ResolvedRefs: True`.

### Certificate

```bash
kubectl -n traefik get certificate
kubectl -n traefik describe certificate wtt-demo | tail -20
```

Expect `wtt-demo` `Ready=True`, and `wtt-demo-staging` also present from the proving run. Nothing alerts on renewal failure, so check this by hand periodically.

### GitOps

```bash
kubectl -n argocd get applications
kubectl -n argocd get application vote-dev-apps -o jsonpath='{.status.sync.status}{" "}{.status.health.status}{"\n"}'
```

Expect `Synced Healthy`. Self-heal is on, `prune` is off.

Drift test, non-destructive — an annotation triggers no pod restart:

```bash
kubectl -n vote-dev annotate deploy/vote drift-test=true --overwrite
sleep 180
kubectl -n vote-dev get deploy vote -o jsonpath='{.metadata.annotations.drift-test}{"\n"}'
```

Expect empty: Argo CD removed it. That is the proof GitOps is real rather than decorative.

### Secret shape, without revealing values

```bash
kubectl -n vote-dev get secret postgres-credentials \
  -o jsonpath='{range $k,$v := .data}{$k}{"\n"}{end}'
```

Expect exactly `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`. Never print the values.

### Data path

```bash
kubectl -n vote-dev exec deploy/redis -- redis-cli LLEN votes
kubectl -n vote-dev exec postgres-0 -- \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT vote, count(*) FROM votes GROUP BY vote ORDER BY vote"'
```

Queue length should be at or near zero. Because of defect D1 the table has no primary key, so a repeat vote adds a row; totals can exceed the number of distinct voters. A known application defect, not a verification failure.

### No credential in any log

```bash
for d in vote result worker; do kubectl -n vote-dev logs deployment/$d --tail=200; done \
  | grep -ciE 'password=|POSTGRES_PASSWORD'
```

Expect `0`.

---

# 4. AWS

```bash
aws eks describe-cluster --name wtt-demo-eks --region eu-north-1 \
  --query 'cluster.{status:status,version:version,publicCidrs:resourcesVpcConfig.publicAccessCidrs}'

aws elbv2 describe-load-balancers --region eu-north-1 \
  --query 'LoadBalancers[].{Name:LoadBalancerName,Type:Type,Scheme:Scheme,DNS:DNSName,State:State.Code}'

aws route53 list-resource-record-sets --hosted-zone-id Z030020038RZDL2JLFT70 \
  --query "ResourceRecordSets[?Name=='wtt-demo.syachin.de.']"
```

**The last two together matter.** The Route 53 alias target is hardcoded in `infra/terraform/iam/dns-demo.tf`. Compare the `DNSName` from the second command with the alias target from the third; they must match. `terraform plan` will not catch a mismatch.

```bash
aws eks list-pod-identity-associations --cluster-name wtt-demo-eks --region eu-north-1
```

### Terraform describes reality

```bash
(cd infra/terraform/network && terraform plan -detailed-exitcode -var-file=../dev.tfvars)
(cd infra/terraform/iam && terraform plan -detailed-exitcode)
(cd infra/terraform/eks && terraform plan -detailed-exitcode -var='api_public_access_cidrs=["YOUR.IP/32"]')
```

Exit code `0` means no changes; `2` means drift. An empty plan in all three roots is the real proof the code describes what is running. **Never recorded.** Block 10.

---

# 5. Repository and CI

```bash
python3 -m pytest tests/ -q                  # expect 12 passed
python3 -m ruff check .
gh run list --limit 5
```

```bash
grep -rnEi 'aws_secret_access_key|BEGIN [A-Z ]*PRIVATE KEY' . \
  --exclude-dir=.git --exclude-dir=.venv
grep -n 'image:' k8s/apps/dev/applications.yaml
```

The image tags in the manifest should match what is running in the cluster.

---

# 6. Troubleshooting

## First five commands

These separate "the edge is broken" from "the application is broken", which is the distinction that matters most here.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://wtt-demo.syachin.de/
kubectl get pods -A --field-selector=status.phase!=Running
kubectl -n traefik get gateway traefik-gateway -o wide
kubectl -n vote-dev port-forward svc/vote 8080:80 &
curl -sS -o /dev/null -w '%{http_code}\n' localhost:8080/ ; kill %1
git log --oneline -10 dev
```

If the port-forward works and the public address does not, the problem is the edge. If both fail, the application.

## The site is unreachable and every pod is healthy

The most likely serious failure, with the most misleading symptoms.

**Check DNS against the live load balancer first.** If the Traefik Service or Helm release was ever recreated, AWS issued a new load balancer and the Route 53 record still points at the old one. The site is down, every pod is healthy, and `terraform plan` is empty.

```bash
dig +short wtt-demo.syachin.de
kubectl -n traefik get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].hostname}{"\n"}'
grep -n 'name ' infra/terraform/iam/dns-demo.tf
```

Recovery: put the current hostname into `dns-demo.tf` and `terraform apply` in the `iam` root. Propagation follows the record TTL.

**Or the Gateway is not programmed:**

```bash
kubectl -n traefik describe gateway traefik-gateway | tail -30
kubectl -n traefik logs deploy/traefik --tail=100
```

| Symptom | Cause | Action |
|---|---|---|
| `PROGRAMMED: False`, `websecure` invalid | Secret `wtt-demo-tls` missing or not issued | Go to the certificate section |
| Routes report `NotAllowedByListeners` | A route names a listener it may not attach to | Compare `sectionName` with the Gateway listeners |
| Routes report `ResolvedRefs: False` | Backend Service or port missing | `kubectl -n vote-dev get svc` |
| Traefik pod not Running | **One replica, no PodDisruptionBudget.** Its loss is a total outage. | `kubectl -n traefik describe pod` |
| Targets unhealthy at the load balancer | Health check path or Proxy Protocol mismatch | Proxy Protocol must be set on both the target group and the entrypoint, or neither |
| Endless redirect in the browser | HTTP and HTTPS sharing one entrypoint | Confirm `http-to-https` attaches only to `web`, and the app routes only to `websecure` |

## The result page loads but never updates

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  'https://wtt-demo.syachin.de/result/socket.io/?EIO=4&transport=polling'
kubectl -n vote-dev logs deploy/result --tail=100
kubectl -n vote-dev exec deploy/redis -- redis-cli LLEN votes
```

A 404 on the Socket.IO path means the `/result/socket.io` rule is missing, reordered, or has acquired a `URLRewrite`. It must have none: the service serves the websocket at that exact path. A growing `LLEN` means the worker is stuck — see the next section.

Open the browser Network tab. This is a case where `curl` reports success and the page is still broken.

## Votes are accepted but the count never changes

The queue is the diagnostic.

```bash
kubectl -n vote-dev exec deploy/redis -- redis-cli LLEN votes
kubectl -n vote-dev get pods -l app=worker
kubectl -n vote-dev logs deploy/worker --tail=100
```

A growing queue means the worker is not draining it. **The worker has no probes at all**, because it exposes no HTTP endpoint, so Kubernetes cannot detect that it is unhealthy and will not restart it. Reading its log is the only signal.

| Log content | Action |
|---|---|
| PostgreSQL connection failure | Check the `postgres` pod, then the Secret |
| Redis connection failure | `kubectl -n vote-dev get pods -l app=redis` |
| Authentication failure | The Secret was rotated without restarting consumers: `kubectl -n vote-dev rollout restart deploy/worker deploy/result` |
| Nothing at all, pod Running | Stuck. `kubectl -n vote-dev delete pod -l app=worker`. |

Defect D2: the worker pops a vote, then checks the database connection, and if it must reconnect it continues the loop **without writing that vote**. The vote is already gone from the queue and is lost.

## PostgreSQL will not start

```bash
kubectl -n vote-dev describe pod postgres-0 | tail -40
kubectl -n vote-dev logs postgres-0 --tail=100
kubectl -n vote-dev get pvc
```

| Symptom | Cause | Action |
|---|---|---|
| `Pending`, volume cannot attach | The pod was scheduled in a different zone from its volume. **A volume exists in one zone only.** | Delete the pod so it reschedules; check node zones against the volume's zone |
| `CrashLoopBackOff`, "not properly shut down" | Normal recovery after an unclean stop | Wait and watch the log |
| `CrashLoopBackOff`, authentication failure | The Secret changed but `PGDATA` holds the old password, which wins | See secret rotation |
| No space left | Volume full | Expansion is enabled: raise the PVC request |

```bash
kubectl -n vote-dev exec postgres-0 -- pg_isready
kubectl -n vote-dev exec postgres-0 -- \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM votes"'
```

Compare the row count with what it was. **If it is lower, data was lost and there is no backup to restore from.**

## The certificate is expired or untrusted

```bash
kubectl -n traefik get certificate
kubectl -n traefik describe certificate wtt-demo | tail -30
kubectl -n traefik get certificaterequest,order,challenge
```

Nothing alerts on renewal failure. A stuck renewal becomes visible only at expiry, about 30 days after cert-manager first tried.

| Symptom | Action |
|---|---|
| Issuer is a staging authority | Point `issuerRef` at `letsencrypt-production` and apply |
| `Challenge` pending with a propagation message | Normal for minutes. If persistent, the solver cannot write to Route 53. |
| `AccessDenied` on `route53:ChangeResourceRecordSets` | Check Pod Identity, below. The policy allows only `TXT` on exactly `_acme-challenge.wtt-demo.syachin.de`, so a changed hostname produces a correct denial that looks like a broken role. |
| `rateLimited` from ACME | **Stop.** Switch to `letsencrypt-staging`, fix there, then switch back. Five duplicates per week. |

```bash
kubectl -n cert-manager exec deploy/cert-manager -- env | grep -i AWS_CONTAINER
aws eks list-pod-identity-associations --cluster-name wtt-demo-eks --region eu-north-1
kubectl -n kube-system get pods -l app.kubernetes.io/name=eks-pod-identity-agent
```

If `AWS_CONTAINER_CREDENTIALS_FULL_URI` is absent, the association is not in effect — usually a service account name mismatch, or the agent not running.

Force a renewal attempt:

```bash
kubectl -n traefik delete certificaterequest -l cert-manager.io/certificate-name=wtt-demo
```

## A secret rotation half-happened

The password inside `PGDATA` is authoritative. Changing only the Secret leaves the application unable to authenticate against a database that still holds the old password.

```bash
python3 scripts/rotate_k8s_postgres_password.py
kubectl -n vote-dev rollout restart deploy/result deploy/worker
kubectl -n vote-dev rollout status deploy/result --timeout=120s
```

The script changes both halves together. Consumers read the Secret only at startup, hence the restart. Never put a password in a command that lands in shell history on a shared machine.

## A release went wrong

Rollback is a Git revert. Argo CD syncs the application, so no `kubectl` is needed for the Deployments.

```bash
git log --oneline -5 -- k8s/apps/dev/applications.yaml
git revert --no-edit <release-commit>
git push
kubectl -n argocd get application vote-dev-apps -o jsonpath='{.status.sync.status}{"\n"}'
kubectl -n vote-dev rollout status deploy/vote --timeout=180s
```

Exercised in `3f9d2a6` and `eac7c13`. For a resource Argo CD does **not** manage — a route, a data service — rollback is `git checkout <commit> -- <file>` followed by `kubectl apply`.

| Reason | Action |
|---|---|
| `ImagePullBackOff` | The tag does not exist: `docker manifest inspect ghcr.io/asyachin/wtt-demo/<svc>:<tag>` |
| `OOMKilled` | Memory limit too low; all three are capped at 512Mi |
| Non-zero exit with a traceback | A bad image. Revert the release commit. |

## Argo CD reverts a manual fix

`selfHeal` reverts a `kubectl edit`, `scale` or `patch` at the next sync. Correct behaviour, and an obstacle during an incident.

```bash
# Preferred: change Git.
# Or, deliberately and temporarily:
kubectl -n argocd patch application vote-dev-apps --type merge \
  -p '{"spec":{"syncPolicy":{"automated":null}}}'
# ... resolve the incident, put the change into Git, then restore automated sync
```

Record in the incident notes that automated sync was disabled, so it is not left off. Access the interface by port-forward; it has no public route.

## CI failed

```bash
gh run list --limit 5
gh run view <run-id> --log-failed
```

| Failing job | Meaning |
|---|---|
| `python-tests` | Ruff or pytest. Run `python3 -m ruff check .` and `python3 -m pytest tests/ -q` locally. |
| `node-check` | `npm ci` or a syntax error in `server.js` |
| `dotnet-check` | Worker build failure |
| `images`, at the Trivy step | A CRITICAL fixable vulnerability. **The image was not pushed.** Upgrade the dependency or add `apt-get upgrade` to the Dockerfile, as in `8625709`. |

The scan runs between build and push, so a vulnerable image never reaches the registry. A failing scan is the gate working, not a pipeline defect.

## Cost looks higher than expected

```bash
aws ce get-cost-and-usage --region us-east-1 \
  --time-period Start=$(date -u -d '7 days ago' +%F),End=$(date -u +%F) \
  --granularity DAILY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE
```

Expect about 0.35 USD per hour. The usual surprise is a resource left by a partial teardown: a load balancer Kubernetes created and Terraform did not remove, a retained volume, or a NAT gateway with its address. See [teardown.md](teardown.md).

## Known gaps, worth knowing before an incident

| Gap | Consequence |
|---|---|
| No monitoring or alerting | Every failure above is found by a human looking, or by a visitor noticing |
| No PostgreSQL backup | Data loss is irreversible. The highest-severity open risk. |
| No health or metrics endpoints | The worker cannot be probed at all |
| Single replica everywhere | No redundancy for Traefik or PostgreSQL |
| Argo CD manages Deployments and Services only | Routing and data services still need manual `kubectl apply` |
| Hardcoded load balancer hostname in Terraform | A silent total outage is possible with nothing reporting it |
| Reclaim policy `Delete` | A mistaken `kubectl delete pvc` destroys all data |
