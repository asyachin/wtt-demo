# Troubleshooting

Failures that are realistic for this platform, ordered by how likely they are. Each entry states how to recognise it, how to confirm it, and how to recover.

Standard setup for everything below:

```bash
export AWS_REGION=eu-north-1
aws eks update-kubeconfig --region eu-north-1 --name wtt-demo-eks
kubectl config set-context --current --namespace=vote-dev
```

## First five commands

Run these in order before forming a theory. They separate "the edge is broken" from "the application is broken", which is the distinction that matters most here.

```bash
# 1. Is the public service answering?
curl -sS -o /dev/null -w '%{http_code}\n' https://wtt-demo.syachin.de/

# 2. Is anything unhealthy?
kubectl get pods -A --field-selector=status.phase!=Running

# 3. Is the edge programmed?
kubectl -n traefik get gateway traefik-gateway -o wide
kubectl get httproute -A

# 4. Bypass the edge entirely
kubectl -n vote-dev port-forward svc/vote 8080:80 &
curl -sS -o /dev/null -w '%{http_code}\n' localhost:8080/ ; kill %1

# 5. What changed?
git log --oneline -10 dev
```

If step 4 works and step 1 does not, the problem is the edge: Traefik, the Gateway, the NLB or DNS. If both fail, it is the application.

---

## The site is unreachable and every pod is healthy

The most likely serious failure in this platform, and the one with the most misleading symptoms.

### Check DNS against the live load balancer first

```bash
dig +short wtt-demo.syachin.de

aws elbv2 describe-load-balancers --region eu-north-1 \
  --query 'LoadBalancers[].{Name:LoadBalancerName,DNS:DNSName,State:State.Code}'

grep -n 'name ' infra/terraform/iam/dns-demo.tf
```

**The Route 53 alias target is hardcoded in Terraform.** If the Traefik `Service` or Helm release was ever deleted and recreated, AWS issued a new NLB with a new hostname, and the Route 53 record still points at the old one. The site is down, every pod is healthy, and `terraform plan` is empty, because from Terraform's point of view nothing changed.

Recovery:

```bash
kubectl -n traefik get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].hostname}{"\n"}'
# Put that value into infra/terraform/iam/dns-demo.tf
cd infra/terraform/iam && terraform apply
```

DNS propagation follows the record's TTL. Background: [../lessons.md](../lessons.md).

### Or the Gateway is not programmed

```bash
kubectl -n traefik get gateway traefik-gateway -o wide
kubectl -n traefik describe gateway traefik-gateway | tail -30
kubectl -n traefik get pods
kubectl -n traefik logs deploy/traefik --tail=100
```

| Symptom | Cause | Action |
|---|---|---|
| `PROGRAMMED: False`, listener `websecure` invalid | Secret `wtt-demo-tls` missing or not yet issued | Go to the certificate section |
| Routes report `NotAllowedByListeners` | A route's `parentRefs` names a listener it may not attach to, or `namespacePolicy` changed | Compare the route's `sectionName` with the Gateway listeners |
| Routes report `ResolvedRefs: False` | The backend Service or port does not exist | `kubectl -n vote-dev get svc` and compare with the route |
| Traefik pod not `Running` | **Single replica, no PodDisruptionBudget.** Its loss is a total outage. | `kubectl -n traefik describe pod` for the reason |
| Traefik logs repeat a CRD or reflector error | Gateway API CRD version mismatch with the chart | Compare the CRD bundle version with the chart's expectation |

### Or a route is attached but matching the wrong rule

```bash
kubectl -n vote-dev describe httproute result | tail -25
```

The `result` route's two rules are order-sensitive. `/result/socket.io` must be matched first and must carry **no** `URLRewrite`; `/result` must carry the rewrite. If the rules are reordered or merged, the page works and live updates break, which looks like a websocket fault and is actually a routing fault.

---

## The result page loads but never updates

Almost always the Socket.IO path.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  'https://wtt-demo.syachin.de/result/socket.io/?EIO=4&transport=polling'

kubectl -n vote-dev logs deploy/result --tail=100
kubectl -n vote-dev exec deploy/redis -- redis-cli LLEN votes
```

| Observation | Meaning |
|---|---|
| Socket.IO path returns 404 | The `/result/socket.io` rule is missing, reordered, or has acquired a `URLRewrite` |
| Socket.IO returns 200 but the browser console shows the connection failing | Check the browser's request URL. The service serves the websocket at `/result/socket.io`, not `/socket.io`. |
| `LLEN votes` is growing | The worker is not consuming. See the next section. |
| Nothing wrong at the edge, counts static | No new votes, or the worker is stuck |

Open the browser Network tab. This is a case where `curl` reports success and the page is still broken.

---

## Votes are accepted but the count never changes

The queue is the diagnostic.

```bash
kubectl -n vote-dev exec deploy/redis -- redis-cli LLEN votes
kubectl -n vote-dev get pods -l app=worker
kubectl -n vote-dev logs deploy/worker --tail=100
```

A growing `LLEN` means the worker is not draining the queue. The worker has **no probes at all** — no HTTP endpoint exists to probe — so Kubernetes cannot detect that it is unhealthy and will not restart it. Reading its log is the only signal.

| Log content | Cause | Action |
|---|---|---|
| PostgreSQL connection failure | Database unavailable, or credentials wrong | Check the `postgres` pod, then the Secret |
| Redis connection failure | Redis restarted or the Service changed | `kubectl -n vote-dev get pods -l app=redis` |
| Authentication failure | The Secret was rotated without restarting consumers | `kubectl -n vote-dev rollout restart deploy/worker deploy/result` |
| Nothing at all, pod `Running` | Stuck. No probe will catch this. | `kubectl -n vote-dev delete pod -l app=worker` |

Known defect D2: the worker pops a vote from Redis, then checks the database connection, and if it must reconnect it continues the loop **without writing that vote**. The vote is already gone from the queue and is lost. A burst of reconnections loses a vote each time.

---

## PostgreSQL will not start

```bash
kubectl -n vote-dev get pods -l app=postgres
kubectl -n vote-dev describe pod postgres-0 | tail -40
kubectl -n vote-dev logs postgres-0 --tail=100
kubectl -n vote-dev get pvc
```

| Symptom | Cause | Action |
|---|---|---|
| `Pending`, volume cannot attach | The pod was scheduled in a different availability zone from its EBS volume. **A volume exists in one zone only.** | Delete the pod so it reschedules; check node zones against the volume's zone |
| `Pending`, no node available | Node capacity, or the pod-density ceiling | `kubectl describe node`; see the pod-density note in [../lessons.md](../lessons.md) |
| `CrashLoopBackOff`, "database system was not properly shut down" | Normal recovery after an unclean stop. The log says so. | Wait and watch |
| `CrashLoopBackOff`, authentication failure | The Secret changed but `PGDATA` still holds the old password. The password in the volume wins. | See the rotation section |
| `CrashLoopBackOff`, no space left | Volume full | Volume expansion is enabled: edit the PVC request upward |
| PVC `Pending` | `WaitForFirstConsumer` means it waits for a pod. If the pod is also pending, both wait. | Resolve the pod first |

Confirm recovery:

```bash
kubectl -n vote-dev exec postgres-0 -- pg_isready
kubectl -n vote-dev exec postgres-0 -- \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM votes"'
```

Compare the row count with what it was before. **If it is lower, data was lost and there is no backup to restore from.** That gap is [Block 06](../blocks/06-data-durability.md).

---

## The certificate is expired or untrusted

```bash
echo | openssl s_client -connect wtt-demo.syachin.de:443 -servername wtt-demo.syachin.de 2>/dev/null \
  | openssl x509 -noout -dates -issuer

kubectl -n traefik get certificate
kubectl -n traefik describe certificate wtt-demo | tail -30
kubectl -n traefik get certificaterequest,order,challenge
```

Nothing alerts on renewal failure, because there is no monitoring. A stuck renewal becomes visible only when the certificate expires, roughly 30 days after cert-manager first tried.

| Symptom | Cause | Action |
|---|---|---|
| Issuer is a staging authority | The `Certificate` points at `letsencrypt-staging` | Switch `issuerRef` to `letsencrypt-production` and apply |
| `Challenge` pending with a DNS propagation message | Normal for a few minutes. If persistent, the solver cannot write to Route 53. | Next row |
| `AccessDenied` on `route53:ChangeResourceRecordSets` | Pod Identity not working, or the policy does not match the record name | See below |
| `rateLimited` from ACME | Too many attempts against production | **Stop.** Switch to `letsencrypt-staging`, fix there, then switch back. The duplicate-certificate limit is five per week. |
| The solver cannot resolve anything | DNS egress from the pod, or the NAT Gateway | `kubectl -n cert-manager exec deploy/cert-manager -- nslookup route53.amazonaws.com` |

Pod Identity diagnosis:

```bash
kubectl -n cert-manager exec deploy/cert-manager -- env | grep -i AWS_CONTAINER
aws eks list-pod-identity-associations --cluster-name wtt-demo-eks --region eu-north-1
kubectl -n kube-system get pods -l app.kubernetes.io/name=eks-pod-identity-agent
```

If `AWS_CONTAINER_CREDENTIALS_FULL_URI` is absent from the pod environment, the association is not in effect. The usual causes are a service account name that does not match the association, or the Pod Identity agent not running.

The policy is deliberately narrow: `TXT` records only, exactly `_acme-challenge.wtt-demo.syachin.de`, in one hosted zone. Changing the hostname without updating `infra/terraform/iam/cert-manager.tf` produces an `AccessDenied` that looks like a broken role and is actually a correct denial.

Force a renewal attempt:

```bash
kubectl -n traefik delete certificaterequest \
  -l cert-manager.io/certificate-name=wtt-demo
```

---

## A secret rotation half-happened

Rotating the PostgreSQL password has two parts, and doing only one produces a confusing failure. The password inside `PGDATA` is authoritative; changing only the Secret leaves the application unable to authenticate against a database that still has the old password.

Use the script rather than improvising:

```bash
python3 scripts/rotate_k8s_postgres_password.py
```

It changes the password inside PostgreSQL and updates the Kubernetes Secret together. Afterwards, restart the consumers, which read the Secret only at startup:

```bash
kubectl -n vote-dev rollout restart deploy/result deploy/worker
kubectl -n vote-dev rollout status deploy/result --timeout=120s
```

Verify without printing any value:

```bash
kubectl -n vote-dev get secret postgres-credentials \
  -o jsonpath='{range $k,$v := .data}{$k}{"\n"}{end}'
kubectl -n vote-dev logs deploy/worker --tail=20
curl -sS -o /dev/null -w '%{http_code}\n' https://wtt-demo.syachin.de/result/
```

If the Secret and the database have already diverged, change the database to match the Secret:

```bash
kubectl -n vote-dev exec -it postgres-0 -- \
  sh -c 'psql -U "$POSTGRES_USER" -c "ALTER USER \"$POSTGRES_USER\" WITH PASSWORD '"'"'<new>'"'"'"'
```

Never put a password in a command that lands in shell history on a shared machine.

---

## A pod is crash-looping after a change

```bash
kubectl -n vote-dev get pods
kubectl -n vote-dev logs <pod> --previous --tail=100
kubectl -n vote-dev describe pod <pod> | grep -A5 'Last State'
```

| Reason | Cause | Action |
|---|---|---|
| `OOMKilled` | Memory limit too low. All three applications are capped at 512Mi. | Raise the limit in `k8s/apps/dev/applications.yaml` and apply |
| `ImagePullBackOff` | The tag does not exist in GHCR | `docker manifest inspect ghcr.io/asyachin/wtt-demo/<svc>:<tag>` |
| Non-zero exit with a traceback | A bad image | Set the previous tag in the manifest and apply |
| `Error` immediately at start | Missing or wrong environment value | Check the Secret keys match what the manifest references |

Rolling back a release today is a manual operation, because there is no GitOps:

```bash
git log --oneline -5 -- k8s/apps/dev/applications.yaml
git checkout <good-commit> -- k8s/apps/dev/applications.yaml
kubectl apply -f k8s/apps/dev/applications.yaml
kubectl -n vote-dev rollout status deploy/vote --timeout=120s
```

After [Block 05](../blocks/05-gitops.md) this becomes `git revert` plus a sync.

---

## A node is lost or not ready

```bash
kubectl get nodes -o wide
kubectl describe node <node> | grep -A10 Conditions
kubectl get pods -A -o wide --field-selector spec.nodeName=<node>
```

The node group runs `min 2, desired 2, max 3` On-Demand instances and replaces a failed node automatically. Watch for a few minutes before intervening.

```bash
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=300s
kubectl delete node <node>
aws ec2 terminate-instances --region eu-north-1 --instance-ids <id>
```

Two things to expect. **Draining the node that hosts PostgreSQL causes an outage** while the pod reschedules and the volume reattaches, and the replacement pod must land in the same availability zone as its EBS volume. And **draining the node that hosts Traefik takes the whole site down**, because there is one replica and no PodDisruptionBudget.

With two nodes and single-replica workloads, a drain is never free. Plan it.

---

## Argo CD reverts a manual fix

Applies after [Block 05](../blocks/05-gitops.md), when `selfHeal` is enabled.

A `kubectl edit`, `kubectl scale` or `kubectl patch` will be reverted at the next sync. That is correct behaviour and the reason GitOps is worth having, but during an incident it is an obstacle.

```bash
# Correct: change Git
# Or, deliberately and temporarily:
argocd app set <app> --sync-policy none
# ... apply the manual fix, resolve the incident ...
# Then put the change into Git and re-enable:
argocd app set <app> --sync-policy automated --self-heal
```

Record in the incident notes that self-healing was disabled, so it is not left off.

Argo CD is not publicly exposed. Access is by port-forward:

```bash
kubectl -n argocd port-forward svc/argocd-server 8443:443
```

---

## Cost looks higher than expected

```bash
aws ce get-cost-and-usage --region us-east-1 \
  --time-period Start=$(date -u -d '7 days ago' +%F),End=$(date -u +%F) \
  --granularity DAILY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE
```

Expect roughly 0.35 USD per hour, dominated by the EKS control plane, two On-Demand `t3.large` nodes and the NAT Gateway. Idle cost is almost the whole cost.

The usual surprise is a resource left behind by a partial teardown: an NLB that Kubernetes created and Terraform did not remove, an EBS volume retained after a PVC was deleted, or a NAT Gateway with its Elastic IP. See [teardown.md](teardown.md).

---

## Escalation and known gaps

Limits worth knowing before an incident, not during one.

| Gap | Consequence |
|---|---|
| No monitoring or alerting | Every failure above is found by a human looking, or by a visitor noticing |
| No backup for PostgreSQL | Data loss is irreversible. The highest-severity open risk. |
| No health or metrics endpoints | The worker cannot be probed at all; `vote` and `result` have readiness but no liveness probe |
| Single replica everywhere | No redundancy for Traefik or PostgreSQL |
| No GitOps yet | Rollback is a manual `kubectl apply` |
| Hardcoded NLB hostname in Terraform | A silent total outage is possible with nothing reporting it |
| Reclaim policy `Delete` | A mistaken `kubectl delete pvc` destroys all data |
