# Runbooks

Every procedure here states when to use it, what to do, and how to confirm it worked. A procedure without a confirmation step is a suggestion.

Procedures are filled in and verified block by block. A section marked "Verified in Block NN" has been run end to end at least once, and any duration given is a measured number rather than an estimate.

## Standard Environment

Run this first. Every procedure below assumes it.

```
export AWS_REGION=eu-north-1
export CLUSTER=wtt-demo
aws eks update-kubeconfig --region $AWS_REGION --name $CLUSTER
kubectl config set-context --current --namespace=vote-prod
```

## Where to Look First

| Question | Command |
|---|---|
| Is the public service answering? | `curl -sf -o /dev/null -w '%{http_code}\n' https://wtt-demo.syachin.de/` |
| Is anything unhealthy? | `kubectl get pods -A --field-selector=status.phase!=Running` |
| Does the cluster match Git? | `argocd app list` |
| Is the queue moving? | Query `vote_queue_length`, see [observability.md](observability.md) |
| What changed recently? | `git log --oneline -10 main` and `argocd app history vote-prod` |

Almost every incident in this system is answered by those five commands. Run them in that order before forming a theory.

---

## Daily Checks

Two minutes. Run once a day while the demonstration is live.

```
# 1. The public service
curl -sf -o /dev/null -w 'vote    %{http_code} in %{time_total}s\n' https://wtt-demo.syachin.de/
curl -sf -o /dev/null -w 'result  %{http_code} in %{time_total}s\n' https://wtt-demo.syachin.de/result
curl -sf -o /dev/null -w 'grafana %{http_code}\n' https://grafana.wtt-demo.syachin.de/api/health

# 2. Nothing is restarting or pending
kubectl get pods -A --field-selector=status.phase!=Running
kubectl -n vote-prod get pods -o wide

# 3. The cluster matches Git
argocd app list -o wide          # every app Synced and Healthy

# 4. No alert is firing
#    See the alerts query in observability.md

# 5. Last night's backup exists and is not empty
aws s3 ls s3://wtt-demo-backups/postgres/ --human-readable | tail -3

# 6. Nodes have capacity
kubectl top nodes
```

Confirm: six checks, no surprise. If any of them is unexpected, go to the matching section below rather than investigating ad hoc.

---

## Deploy a New Version

No deployment is ever performed with `kubectl` or `helm`. A deployment is a Git commit. The full workflow is in [../dev/git-workflow.md](../dev/git-workflow.md); this is the operational short form.

```
# 1. Read the tag currently running in development
grep -r 'tag:' deploy/helm/wtt-vote/values-dev.yaml

# 2. Confirm development is healthy
argocd app get vote-dev
kubectl -n vote-dev port-forward svc/vote 8080:80 &
pytest -m e2e --base-url http://localhost:8080
kill %1

# 3. Verify the production images carry a valid signature
cosign verify ghcr.io/asyachin/wtt-vote:<tag> \
  --certificate-identity-regexp 'https://github.com/asyachin/wttcampusone/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

# 4. Promote: copy the same tag into values-prod.yaml, on a branch, in a pull request
git switch -c promote/<tag>
#    edit deploy/helm/wtt-vote/values-prod.yaml
git commit -am "deploy(prod): promote <tag>"
gh pr create --base main --title "Promote <tag> to production"

# 5. Merge by hand. Then watch Argo CD converge.
argocd app wait vote-prod --health --timeout 300
kubectl -n vote-prod rollout status deployment/vote deployment/result deployment/worker
```

Confirm:

```
kubectl -n vote-prod get deployment vote -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
pytest -m e2e --base-url https://wtt-demo.syachin.de
```

The promotion diff must contain nothing but image tags. If it also contains a chart change, split it, so that reverting the release does not also revert the chart.

---

## Roll Back a Release

Use when a promotion made production worse.

```
# 1. Find the promotion commit
git log --oneline -5 main

# 2. Revert it
git switch main && git pull --ff-only
git revert --no-edit <promotion commit>
git push

# 3. Argo CD picks it up within its sync interval. To not wait:
argocd app sync vote-prod
argocd app wait vote-prod --health --timeout 300
```

Confirm:

```
kubectl -n vote-prod get deployment vote -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
pytest -m e2e --base-url https://wtt-demo.syachin.de
```

Expected duration: under 5 minutes, limited by the Argo CD sync interval and the rolling update.

Do not use `kubectl rollout undo` or `helm rollback`. Argo CD has `selfHeal` enabled and will revert either of them within the next sync, which produces a confusing flap and leaves the cluster in a state Git does not describe.

If the bad release included a database migration, roll the database back first, using the restore procedure below, and only then revert the image. A new image against a migrated schema usually still works; an old image against a migrated schema often does not.

---

## Alert: VoteServiceDown

`VoteServiceDown` — `up{job="vote"} == 0` for 2 minutes. Critical. The voting page is unreachable.

```
# 1. Confirm from outside
curl -sf -o /dev/null -w '%{http_code}\n' https://wtt-demo.syachin.de/

# 2. Pod state
kubectl -n vote-prod get pods -l app=vote
kubectl -n vote-prod describe pod -l app=vote | tail -30
kubectl -n vote-prod logs -l app=vote --tail=100 --prefix
```

| What you see | Cause | Action |
|---|---|---|
| `ImagePullBackOff` | The promoted tag does not exist in GHCR | Roll back the release |
| `CrashLoopBackOff` with a traceback | A bad release | Roll back the release |
| `Pending`, no node available | Spot capacity was reclaimed | See Replace a Failed Node |
| Pods are `Running` and ready, but the alert fires | Prometheus cannot scrape them | See Diagnose a Network Policy Problem |
| Pods are ready, and the external request fails | The edge path is broken | Go to `GatewayNotProgrammed`. This alert is then a symptom, and the inhibition rule should have suppressed it. |

Confirm: `curl` returns 200 and the alert clears within 5 minutes.

---

## Alert: ResultServiceDown

`ResultServiceDown` — `up{job="result"} == 0` for 2 minutes. Critical.

Same procedure as above, with `-l app=result` and the `/result` path. One extra cause is specific to this service: if the pods are ready but the page does not update, the websocket is failing rather than the service.

```
kubectl -n vote-prod logs -l app=result --tail=100
kubectl -n vote-prod exec deploy/result -- curl -sf localhost/readyz
```

A 503 from `/readyz` names the failing dependency, which for this service is always PostgreSQL. In that case go to `PostgresDown`; this alert is a symptom.

Remember that the Socket.IO path is `/result/socket.io`, not the default. An `HTTPRoute` rule narrowed from `PathPrefix /result` to `/socket.io` breaks live updates while leaving the page itself working, which is a confusing failure. `test_websocket_upgrade_succeeds` in Block 05 catches it in `kind` before it reaches a cluster.

---

## Alert: WorkerNotProcessing

`WorkerNotProcessing` — `vote_queue_length > 50` for 5 minutes. Critical. Votes are being accepted but not stored.

This is the most informative alert in the system. The queue sits between the web tier and the database tier, so it grows whenever anything downstream fails.

```
# 1. Is the worker running at all?
kubectl -n vote-prod get pods -l app=worker
kubectl -n vote-prod logs -l app=worker --tail=100

# 2. What does the worker think about its dependencies?
kubectl -n vote-prod exec deploy/worker -- curl -sf localhost:9090/readyz

# 3. How deep is the queue, directly?
kubectl -n vote-prod exec redis-0 -- redis-cli LLEN votes
```

| What you see | Cause | Action |
|---|---|---|
| No worker pod | Scaled to zero, or evicted | `kubectl -n vote-prod get deployment worker`, then check the Git value |
| `readyz` reports PostgreSQL unreachable | The database is the real problem | Go to `PostgresDown` |
| `readyz` reports Redis unreachable | A network policy or a Redis restart | See Diagnose a Network Policy Problem |
| The worker is running and the queue still grows | Processing is slower than the arrival rate | `kubectl -n vote-prod scale deployment/worker --replicas=3` as an emergency measure, then set the value in Git so Argo CD does not revert it |
| The worker log repeats a database error | A credential or schema problem | Check the secret and the migration Job |

Confirm: `vote_queue_length` returns to near zero, and a new vote appears on the result page within 10 seconds.

Note that votes already taken from Redis and not yet written are lost if the worker is killed at the wrong moment. This is a known limitation of the application, recorded in [../arch/application.md](../arch/application.md).

---

## Alert: VoteErrorRateHigh

`VoteErrorRateHigh` — the 5xx share is above 5 percent for 5 minutes. Warning. The service is failing without crashing, which is the hardest state to notice without this alert.

```
kubectl -n vote-prod logs -l app=vote --tail=200 | grep -E ' 5[0-9]{2} '
kubectl -n vote-prod exec deploy/vote -- curl -sf localhost/readyz
kubectl -n vote-prod top pods
```

Usual causes, in order of likelihood: Redis is slow or refusing connections; the pod is at its memory limit and gunicorn workers are being killed; a dependency timeout is firing under load.

```
# Check whether the limit is the problem
kubectl -n vote-prod describe pod -l app=vote | grep -A3 'Last State'
```

If a container was `OOMKilled`, raise the memory limit in the Helm value file, commit, and let Argo CD apply it. Do not patch the deployment directly.

Confirm: the error rate returns below 1 percent, and `/readyz` is 200 on every pod.

---

## Alert: PostgresDown

`PostgresDown` — `up{job="postgres"} == 0` for 1 minute. Critical. The system of record is unavailable. Votes continue to queue in Redis and are written once the database returns, so this is an outage of the result page rather than a loss of data.

```
kubectl -n vote-prod get pods -l app=postgres
kubectl -n vote-prod describe pod postgres-0 | tail -40
kubectl -n vote-prod logs postgres-0 --tail=100
kubectl -n vote-prod get pvc
```

| What you see | Cause | Action |
|---|---|---|
| `Pending`, the volume cannot attach | The pod moved to a node in another availability zone. An EBS volume is tied to one zone. | Delete the pod so it reschedules into the original zone, or check the node affinity |
| `CrashLoopBackOff`, log mentions "no space left" | The volume is full | See Expand a Volume |
| `CrashLoopBackOff`, log mentions authentication | A rotation was done incompletely | See Rotate a Secret |
| The volume is lost | The node and the volume are both gone | See Restore the Database |
| `Running` but not ready | Still performing recovery after an unclean shutdown. The log says so. | Wait, and watch the log |

Confirm:

```
kubectl -n vote-prod exec postgres-0 -- pg_isready
kubectl -n vote-prod exec postgres-0 -- psql -U postgres -d votes -c 'SELECT count(*) FROM votes'
curl -sf https://wtt-demo.syachin.de/result -o /dev/null && echo ok
```

Check the row count against what it was before the incident. If it is lower, data was lost and the restore procedure applies.

---

## Alert: PostgresDiskFillingUp

`PostgresDiskFillingUp` — projected to fill within 24 hours. Warning. This is a prevention alert; act while there is still room.

```
kubectl -n vote-prod exec postgres-0 -- df -h /var/lib/postgresql/data
kubectl -n vote-prod exec postgres-0 -- psql -U postgres -d votes -c \
  "SELECT pg_size_pretty(pg_database_size('votes'))"
```

For this application the table is tiny, so unexpected growth usually means write-ahead log files accumulating or a runaway insert loop rather than real data. Check the row count before expanding anything.

Then follow Expand a Volume.

---

## Alert: BackupJobFailed

`BackupJobFailed` — no successful backup in 26 hours. Critical. A backup that stops silently is worse than no backup, because it is trusted.

```
kubectl -n vote-prod get cronjob postgres-backup
kubectl -n vote-prod get jobs -l app=postgres-backup --sort-by=.metadata.creationTimestamp
kubectl -n vote-prod logs job/<most recent job>
aws s3 ls s3://wtt-demo-backups/postgres/ --human-readable | tail -5
```

| What you see | Cause | Action |
|---|---|---|
| No Job was created | The CronJob is suspended, or the schedule is wrong | `kubectl -n vote-prod get cronjob postgres-backup -o yaml` and compare with Git |
| The Job failed on `AccessDenied` | The IRSA role or the bucket policy changed | Check the service account annotation and the role trust policy |
| The Job failed on a connection error | PostgreSQL was unavailable at 02:00 | Run it by hand now, then investigate why |
| The Job succeeded but the object is 0 bytes | `pg_dump` failed silently inside a pipe | Add `set -o pipefail` to the job script. This is a real trap. |

Run a backup by hand:

```
kubectl -n vote-prod create job --from=cronjob/postgres-backup backup-manual-$(date +%s)
kubectl -n vote-prod logs -f job/backup-manual-<timestamp>
aws s3 ls s3://wtt-demo-backups/postgres/ --human-readable | tail -1
```

Confirm: a new object exists, its size is plausible, and the alert clears. Then verify it can actually be restored, using the restore procedure against a throwaway namespace. A backup is only proven by a restore.

---

## Alert: CertificateRenewalFailed

`CertificateRenewalFailed` — a cert-manager `Certificate` has reported `Ready=False` for an hour. Critical, and it fires about 30 days before a browser would complain. That margin is the whole point; use it rather than waiting.

```
# 1. Which certificate, and what does it say?
kubectl -n traefik get certificate
kubectl -n traefik describe certificate wtt-demo-tls | tail -30

# 2. Walk the chain of objects. cert-manager creates one per stage.
kubectl -n traefik get certificaterequest,order,challenge
kubectl -n traefik describe challenge | tail -40

# 3. Is the controller healthy?
kubectl -n cert-manager get pods
kubectl -n cert-manager logs deploy/cert-manager --tail=100
```

| What you see | Cause | Action |
|---|---|---|
| The `Challenge` is `pending` with a DNS propagation message | Normal for a few minutes. If it persists, the solver cannot write to Route 53. | Check the cert-manager IRSA role and the hosted zone identifier in the `ClusterIssuer` |
| `AccessDenied` on `route53:ChangeResourceRecordSets` | The IRSA trust policy or the service account annotation is wrong | Compare the service account annotation with the role trust policy |
| `urn:ietf:params:acme:error:rateLimited` | Too many attempts against Let's Encrypt production | Stop. Switch the `Certificate` to `letsencrypt-staging`, fix the problem there, and only then switch back. The duplicate-certificate limit is 5 per week. |
| The issuer in the served certificate is a staging authority | A debugging session was left pointing at staging | Switch the `Certificate` back to `letsencrypt-prod` in Git, and confirm with the `openssl` command below |
| The solver pod cannot resolve anything | A default-deny network policy with no CoreDNS egress rule in the `cert-manager` namespace | See Diagnose a Routing or Network Policy Problem |

Force a renewal attempt:

```
kubectl cert-manager renew wtt-demo-tls -n traefik
# or, without the plugin:
kubectl -n traefik delete certificaterequest -l cert-manager.io/certificate-name=wtt-demo-tls
```

Confirm:

```
kubectl -n traefik get certificate wtt-demo-tls
echo | openssl s_client -connect wtt-demo.syachin.de:443 -servername wtt-demo.syachin.de 2>/dev/null \
  | openssl x509 -noout -dates -issuer -subject
```

The issuer must name Let's Encrypt, not a staging authority, and the expiry must be about 90 days out.

---

## Alert: CertificateExpiringSoon

`CertificateExpiringSoon` — fewer than 14 days remaining on the served certificate. Warning, and by this point most of the renewal margin is gone. Treat it as the second warning, not the first.

Follow the renewal procedure above. If the renewal cannot be made to work within a day, the fallback is a manual issuance against the staging issuer to confirm the solver, then production.

---

## Alert: GatewayNotProgrammed and TraefikDown

`GatewayNotProgrammed` or `TraefikDown`. Critical. Every public endpoint is unreachable, including Grafana, while the application pods are healthy. These two alerts suppress `VoteServiceDown` and `ResultServiceDown`, because those are symptoms.

```
# 1. Confirm from outside
curl -sf -o /dev/null -w '%{http_code}\n' https://wtt-demo.syachin.de/

# 2. Is Traefik running?
kubectl -n traefik get pods -o wide
kubectl -n traefik logs deploy/traefik --tail=100

# 3. What does the Gateway say about itself?
kubectl -n traefik describe gateway wtt-demo | tail -40

# 4. Are the routes still attached?
kubectl get httproute -A
kubectl -n vote-prod describe httproute vote | tail -20

# 5. Is the load balancer healthy?
kubectl -n traefik get svc traefik
aws elbv2 describe-target-health --region $AWS_REGION --target-group-arn <arn>
```

| What you see | Cause | Action |
|---|---|---|
| `Programmed=False`, listener `Invalid` | The certificate `Secret` is missing or not yet issued | Go to `CertificateRenewalFailed` |
| Routes report `NotAllowedByListeners` | The namespace lost the gateway attachment label | Check the namespace labels against `allowedRoutes` in the `Gateway` |
| Routes report `ResolvedRefs=False` | The backend Service or port does not exist, or a `ReferenceGrant` is missing | `kubectl -n vote-prod get svc` and compare with the route |
| Traefik log repeats a reflector error about `v1alpha2.TCPRoute` | `experimentalChannel` is enabled without the Experimental CRDs. This disables the whole Gateway provider, so every route 404s. | Set `experimentalChannel: false` in Git. `test_experimental_channel_disabled` should have caught this. |
| Traefik pods are ready and the NLB targets are unhealthy | The health check path or the Proxy Protocol setting is mismatched | Proxy Protocol must be on both the target group and the entrypoint, or neither |
| An endless redirect in the browser | The HTTP and HTTPS listeners are sharing one entrypoint | Confirm port 80 maps to entrypoint 8000 and port 443 to 8443, and that the redirect filter is only on the HTTP listener |
| All pods are healthy, nothing reaches them | A default-deny network policy without a rule for the `traefik` namespace | See Diagnose a Routing or Network Policy Problem |

Confirm:

```
kubectl -n traefik get gateway wtt-demo   # PROGRAMMED True
pytest -m e2e --base-url https://wtt-demo.syachin.de
```

---

## Alert: NodeNotReady

`NodeNotReady` — a node has not been ready for 5 minutes. Warning. Spot reclamation is expected behaviour; a node stuck in `NotReady` is not.

```
kubectl get nodes -o wide
kubectl describe node <node> | grep -A10 Conditions
kubectl describe node <node> | grep -A10 'Taints\|Events'
```

If the node was reclaimed as Spot capacity, the node group replaces it automatically. Watch for a few minutes. If it does not recover, follow Replace a Failed Node.

Confirm: two nodes are `Ready` and no pod is `Pending`.

---

## Alert: PodCrashLooping

`PodCrashLooping` — more than 3 restarts in 15 minutes. Warning. Almost always a bad release or a resource limit.

```
kubectl -n vote-prod get pods
kubectl -n vote-prod logs <pod> --previous --tail=100
kubectl -n vote-prod describe pod <pod> | grep -A5 'Last State'
```

| Exit reason | Cause | Action |
|---|---|---|
| `OOMKilled` | The memory limit is too low | Raise the limit in the Helm value file, commit |
| A non-zero exit with a traceback | A bad release | Roll back the release |
| `Error` immediately after start | A missing or wrong environment variable or secret | Check the `ExternalSecret` status |
| Liveness probe failures | The probe is too strict, or the process is genuinely stuck | Compare the probe timings with the real startup time |

Note the design rule from [../arch/application.md](../arch/application.md): `/healthz` must never check a dependency. If a pod restarts whenever Redis is slow, the liveness probe is pointing at `/readyz` by mistake.

---

## Restore the Database

Use when data has been lost or corrupted. Verified in Block 11, with the measured duration recorded there.

```
# 1. Pick a backup
aws s3 ls s3://wtt-demo-backups/postgres/ --human-readable

# 2. Stop the writers, so nothing writes during the restore.
#    Votes keep queueing in Redis and are processed afterwards.
kubectl -n vote-prod scale deployment/worker --replicas=0
kubectl -n vote-prod scale deployment/result --replicas=0

# 3. Restore, using the script exactly as written. Do not improvise.
./scripts/restore-postgres.sh postgres/2026-10-14.dump

# 4. Bring the writers back
kubectl -n vote-prod scale deployment/worker --replicas=1
kubectl -n vote-prod scale deployment/result --replicas=2
```

Confirm:

```
kubectl -n vote-prod exec postgres-0 -- \
  psql -U postgres -d votes -c 'SELECT vote, count(*) FROM votes GROUP BY vote'
curl -sf https://wtt-demo.syachin.de/result -o /dev/null && echo ok
pytest -m e2e --base-url https://wtt-demo.syachin.de
```

Two notes. The scale commands are a deliberate exception to the "never change the cluster by hand" rule, because an incident is not a normal operation; set the replicas back to the values in Git afterwards, or Argo CD will do it for you. And if an undocumented step was needed to make this work, the documentation is wrong, and fixing the documentation is part of closing the incident.

---

## Rotate a Secret

See [secrets.md](secrets.md), which holds the full procedure for each secret, the rollback path, and the verification commands. The single step that is most often forgotten: changing the value in AWS Secrets Manager does not change the password inside PostgreSQL. Both have to happen.

---

## Scale the Application

Scaling is a Git change, not a command.

```
# edit deploy/helm/wtt-vote/values-prod.yaml
#   vote:   replicaCount: 4
git commit -am "deploy(prod): scale vote to 4 replicas"
git push
argocd app sync vote-prod
```

Confirm:

```
kubectl -n vote-prod get deployment vote
kubectl -n vote-prod get pods -l app=vote
```

During an incident, `kubectl scale` is acceptable as an emergency measure. Argo CD will revert it at the next sync, so the value must then be put into Git. Note what the ceiling is: the cluster has two `t3.small` nodes, so about 4 GiB of allocatable memory in total. Scaling past the node capacity produces `Pending` pods, not more throughput. To grow beyond that, raise the node group size in Terraform.

`worker` is the one component that does not benefit from many replicas. It polls a single Redis list, so two workers mostly compete for the same `LPOP`. Three is a sensible maximum.

---

## Expand a Volume

The `gp3` storage class allows expansion, and PostgreSQL supports it online.

```
# 1. Change the size in Git
# edit deploy/helm/wtt-vote/values-prod.yaml
#   postgres: persistence: size: 20Gi
git commit -am "deploy(prod): expand the postgres volume to 20Gi"
git push
argocd app sync vote-prod

# 2. A StatefulSet does not update its volumeClaimTemplate in place.
#    Patch the existing claim as well.
kubectl -n vote-prod patch pvc data-postgres-0 \
  -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'

# 3. Watch the expansion
kubectl -n vote-prod get pvc data-postgres-0 -w
```

Confirm:

```
kubectl -n vote-prod exec postgres-0 -- df -h /var/lib/postgresql/data
```

Two warnings. A volume can only grow, never shrink; a size chosen too large is permanent. And a volume can only be expanded once every six hours, which is an EBS limit, so pick the new size with some headroom rather than expanding twice.

---

## Replace a Failed Node

```
# 1. Identify it
kubectl get nodes -o wide
kubectl describe node <node> | grep -A10 Conditions

# 2. Move the workloads off
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=300s

# 3. Delete it and let the node group replace it
kubectl delete node <node>
aws ec2 terminate-instances --region $AWS_REGION --instance-ids <instance id>

# 4. Wait for the replacement
kubectl get nodes -w
```

Confirm:

```
kubectl get nodes                                        # two nodes Ready
kubectl -n vote-prod get pods -o wide                    # nothing Pending
pytest -m e2e --base-url https://wtt-demo.syachin.de
```

The draining step blocks if the PodDisruptionBudget cannot be satisfied, which is the budget doing its job. With only two nodes and two replicas, draining one node means `minAvailable: 1` is exactly met, so it should succeed. If it blocks, scale the deployment up first so there is a spare replica.

PostgreSQL is a single pod on an EBS volume, so draining its node causes a short outage while the pod reschedules and the volume reattaches. The volume can only attach within its own availability zone, so the replacement pod must land in the same zone. If it stays `Pending`, check the node availability zones against the volume's zone.

If Spot capacity is unavailable repeatedly, switch to the On-Demand node group that Block 06 defines with zero desired capacity:

```
# edit infra/terraform/env/platform/terraform.tfvars
#   ondemand_desired_size = 2
#   spot_desired_size     = 0
cd infra/terraform/env/platform && terraform apply
```

---

## Diagnose a Routing or Network Policy Problem

Use when a service reports a dependency as unreachable although both pods are running, or when the site is unreachable from outside while every pod is healthy. This is the most common self-inflicted failure after Block 12.

Start by deciding which side of the edge the problem is on:

```
# From outside
curl -sf -o /dev/null -w '%{http_code}\n' https://wtt-demo.syachin.de/

# From inside the cluster, bypassing Traefik entirely
kubectl -n vote-prod port-forward svc/vote 8080:80 &
curl -sf -o /dev/null -w '%{http_code}\n' localhost:8080/
kill %1
```

If the port-forward works and the public address does not, the problem is the edge or a policy blocking the `traefik` namespace. Go to `GatewayNotProgrammed`. If both fail, it is the application or a policy between the application pods, and the rest of this section applies.

```
# 1. What does the service itself say?
kubectl -n vote-prod exec deploy/vote   -- curl -sf localhost/readyz
kubectl -n vote-prod exec deploy/result -- curl -sf localhost/readyz
kubectl -n vote-prod exec deploy/worker -- curl -sf localhost:9090/readyz

# 2. Test the connection directly, from the pod that needs it
kubectl -n vote-prod exec deploy/vote   -- nc -zv redis 6379
kubectl -n vote-prod exec deploy/worker -- nc -zv postgres 5432
kubectl -n vote-prod exec deploy/result -- nc -zv postgres 5432

# 3. Is DNS working? A default-deny policy that forgets CoreDNS breaks everything.
kubectl -n vote-prod exec deploy/vote -- nslookup redis

# 4. Which policies apply?
kubectl -n vote-prod get networkpolicy
kubectl -n vote-prod describe networkpolicy
```

| Symptom | Cause |
|---|---|
| Every name fails to resolve | The default-deny policy has no egress rule for CoreDNS on UDP and TCP port 53 |
| Names resolve, connections time out | A missing allow rule between those two pod selectors |
| Prometheus shows every target as down | A missing allow rule for the monitoring namespace to the metrics ports |
| The site is unreachable, every pod is healthy, a port-forward works | A missing ingress rule allowing the `traefik` namespace to reach `vote` and `result` |
| A certificate renewal starts failing weeks after a policy change | The `cert-manager` namespace lost its CoreDNS egress rule, so the DNS-01 solver cannot resolve the Route 53 endpoint. This fails silently until `CertificateRenewalFailed` fires. |
| It works in `vote-dev` and not in `vote-prod` | The two policy sets have drifted. `test_dev_and_prod_differ_only_in_allowed_keys` should have caught this; find out why it did not. |

Fix in Git, never with `kubectl edit`. Add one allow rule, sync, retest, repeat. Adding several rules at once makes it impossible to tell which one was needed.

```
kubectl -n vote-prod delete networkpolicy default-deny   # only as a temporary measure
```

Deleting the default-deny policy restores service immediately and reopens the namespace. Argo CD will put it back at the next sync, which is correct, so use this only to confirm that a policy is the cause.

---

## Recover Argo CD

Use when Argo CD itself is unhealthy. The applications keep running while Argo CD is down; what stops is reconciliation.

```
kubectl -n argocd get pods
kubectl -n argocd logs deploy/argocd-repo-server --tail=100
kubectl -n argocd logs statefulset/argocd-application-controller --tail=100
```

| Symptom | Cause | Action |
|---|---|---|
| `ComparisonError`, cannot fetch the repository | A credential or network problem | Check the repository secret and the egress policy on the `argocd` namespace |
| An application is stuck `Progressing` | It is waiting on a resource that will never become healthy | `argocd app get <app> --hard-refresh`, then look at the unhealthy resource |
| `OutOfSync` and it will not sync | A hook or a finalizer is stuck | `argocd app terminate-op <app>`, then sync again |
| The whole installation is broken | Something changed outside Git | Reinstall with Terraform. Argo CD holds no state that matters; everything is in Git. |

Reinstall:

```
cd infra/terraform/env/platform
terraform apply -replace='module.platform.helm_release.argocd'
argocd app list                        # the app-of-apps rebuilds everything
```

Confirm:

```
argocd app list -o wide                # every app Synced and Healthy
```

The admin password is in AWS Secrets Manager; see [secrets.md](secrets.md).

---

## Rebuild the Platform From Nothing

The full disaster recovery procedure. Rehearsed and measured in Block 13, where the measured duration is recorded.

Assumes the AWS account exists, the Route 53 hosted zone `syachin.de` exists, the Terraform state bucket exists, and the GitHub repository exists.

```
# 1. Infrastructure
cd infra/terraform/env/platform
terraform init
terraform apply                       # expect 15 to 20 minutes

# 2. Cluster access
aws eks update-kubeconfig --region eu-north-1 --name wtt-demo
kubectl get nodes

# 3. Argo CD is installed by the same apply. Confirm it and let it rebuild the rest.
kubectl -n argocd get pods
argocd app list                       # expect root, vote-dev, vote-prod, observability

# 4. Secrets are read from AWS Secrets Manager, which survived. Confirm delivery.
kubectl -n vote-prod get externalsecret

# 5. Restore the data
./scripts/restore-postgres.sh postgres/<most recent backup>

# 6. The certificate is re-issued by cert-manager and the records are rewritten by
#    ExternalDNS. This is the slowest part of the recovery, because it includes a
#    DNS-01 challenge and DNS propagation. Watch it rather than guessing.
kubectl -n traefik get certificate -w
kubectl -n traefik get gateway wtt-demo        # wait for PROGRAMMED True
dig +short wtt-demo.syachin.de
echo | openssl s_client -connect wtt-demo.syachin.de:443 \
  -servername wtt-demo.syachin.de 2>/dev/null | openssl x509 -noout -dates -issuer
```

If the certificate does not issue, check the Let's Encrypt rate limit before anything else. A rebuild drill run more than five times in a week will hit the duplicate-certificate limit, and the correct response is to use the staging issuer for the drill rather than to retry.

Confirm:

```
pytest -m e2e --base-url https://wtt-demo.syachin.de
pytest -m platform --namespace vote-prod
```

What survives a total cluster loss, and what does not:

| Survives | Does not survive |
|---|---|
| All source code, manifests, and Terraform, in GitHub | Any state that was only in the cluster |
| All secrets, in AWS Secrets Manager | Votes still in the Redis queue |
| All container images, in GHCR | Votes written since the last nightly backup |
| Database backups, in S3 | Prometheus metric history |
| Terraform state, in the versioned S3 bucket | The TLS certificate and its private key, which are re-issued rather than restored |
| The Route 53 hosted zone | |

The gap between the last backup and the failure is the accepted data loss window: up to 24 hours. For a demonstration this is the right trade-off, and it is stated here so that nobody assumes otherwise.

---

## Tear Everything Down and Confirm Zero Cost

Run when the interview process ends. Order matters: Kubernetes-created AWS resources must go before the cluster, or they are orphaned and keep billing.

```
# 1. Delete the Traefik Service of type LoadBalancer, which is what owns the NLB.
#    Deleting the routes does not remove it. Uninstalling the release does.
kubectl -n traefik delete svc traefik

# 2. Confirm no load balancer remains
aws elbv2 describe-load-balancers --region eu-north-1 \
  --query 'LoadBalancers[].LoadBalancerName'

# 3. Release the persistent volumes. The storage class retains them, so delete them explicitly.
kubectl -n vote-prod delete pvc --all
kubectl -n vote-dev  delete pvc --all
kubectl -n observability delete pvc --all
aws ec2 describe-volumes --region eu-north-1 \
  --filters Name=status,Values=available --query 'Volumes[].VolumeId'

# 4. Destroy the infrastructure
cd infra/terraform/env/platform
terraform destroy                     # expect 15 to 20 minutes

# 5. Decide what to keep. These are cheap and hold the recovery path.
#    Keep: the S3 backup bucket, the Terraform state bucket, the Route 53 hosted zone,
#          the Secrets Manager entries.
#    Delete only if the project is being abandoned entirely.
```

Confirm, 24 hours later:

```
aws ce get-cost-and-usage --region us-east-1 \
  --time-period Start=$(date -u -d yesterday +%F),End=$(date -u +%F) \
  --granularity DAILY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE

# Nothing left that bills by the hour
aws eks list-clusters --region eu-north-1
aws ec2 describe-instances --region eu-north-1 \
  --filters Name=instance-state-name,Values=running --query 'Reservations[].Instances[].InstanceId'
aws ec2 describe-nat-gateways --region eu-north-1 \
  --filter Name=state,Values=available --query 'NatGateways[].NatGatewayId'
aws ec2 describe-volumes --region eu-north-1 --query 'Volumes[].VolumeId'
aws elbv2 describe-load-balancers --region eu-north-1 --query 'LoadBalancers[].LoadBalancerArn'
```

Every one of those five queries must return an empty list. The three resources that are most often left behind and keep billing are the NLB created by the Traefik `Service` rather than by Terraform, an EBS volume kept by the `Retain` reclaim policy, and a NAT gateway with an attached elastic IP address. Check all three by name.

Two things that are not billed but should be cleaned up as well: the Route 53 records written by ExternalDNS, and the TXT challenge records written by cert-manager. Both components remove their own records when their objects are deleted, so deleting the routes and the `Certificate` before `terraform destroy` leaves the hosted zone clean. Doing it in the other order leaves orphaned records that have to be removed by hand.

```
aws route53 list-resource-record-sets --hosted-zone-id <zone id> \
  --query "ResourceRecordSets[?contains(Name, 'wtt-demo')].[Name,Type]" --output text
```
