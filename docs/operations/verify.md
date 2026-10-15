# Verification

Layered checks, from the outside in. Section 1 needs nothing but a shell and the internet, and is referenced by every block's Definition of Done.

Results marked **verified 15 Oct 2026** were run from a workstation outside AWS and are reproducible by any reader. Checks needing cluster or AWS access were not run; they are marked accordingly.

## 1. Public service — no credentials needed

The gate for every block. If any of this fails, the demonstration is broken.

```bash
HOST=wtt-demo.syachin.de

# DNS resolves to the load balancer, one address per availability zone
dig +short $HOST

# Vote page
curl -sS -o /dev/null -w 'vote        %{http_code}\n' https://$HOST/

# Result page, both forms
curl -sS -o /dev/null -w 'result      %{http_code} %{redirect_url}\n' https://$HOST/result
curl -sS -o /dev/null -w 'result/     %{http_code}\n' https://$HOST/result/

# The asset whose failure was invisible to a status-code check
curl -sS -o /dev/null -w 'result js   %{http_code}\n' https://$HOST/result/app.js

# Socket.IO through the Gateway
curl -sS -o /dev/null -w 'socket.io   %{http_code}\n' \
  "https://$HOST/result/socket.io/?EIO=4&transport=polling"
```

Expected, and verified 15 Oct 2026:

```
dig          13.61.87.220, 13.60.127.160
vote         200
result       301  https://wtt-demo.syachin.de/result/
result/      200
result js    200
socket.io    200
```

### Certificate

```bash
echo | openssl s_client -connect $HOST:443 -servername $HOST 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

Expected, and verified 15 Oct 2026:

```
subject=CN = wtt-demo.syachin.de
issuer=C = US, O = Let's Encrypt, CN = YR2
notBefore=Oct 14 18:21:55 2026 GMT
notAfter=Jan 12 18:21:54 2027 GMT
X509v3 Subject Alternative Name:
    DNS:wtt-demo.syachin.de
```

The issuer must name Let's Encrypt and not a staging authority. A staging certificate left in place produces a browser warning while every `curl` check above still passes, because `curl` reports the handshake result separately from the trust decision.

One name, no wildcard. That is the implemented design.

### No blocked active content

The check that would have caught defect D5. Nothing in the served HTML may be referenced over plain `http://`.

```bash
for path in / /result/; do
  echo "== $path"
  curl -sS "https://$HOST$path" | grep -oE '(src|href)="[^"]+"' | sort -u
done
```

Verified 15 Oct 2026: no `http://` reference on either page. Two external references remain, both resolving over HTTPS:

```
href="https://maxcdn.bootstrapcdn.com/font-awesome/4.4.0/css/font-awesome.min.css"
src="https://code.jquery.com/jquery-3.7.1.min.js"
src="//cdnjs.cloudflare.com/ajax/libs/jquery-cookie/1.4.1/jquery.cookie.js"
```

The protocol-relative `//cdnjs...` form resolves to HTTPS on an HTTPS page and is **not** blocked. It is a legacy pattern, tracked as D5b, not a failure of this check.

Every external asset must also resolve:

```bash
curl -sS -o /dev/null -w 'jquery   %{http_code}\n' https://code.jquery.com/jquery-3.7.1.min.js
curl -sS -o /dev/null -w 'cookie   %{http_code}\n' https://cdnjs.cloudflare.com/ajax/libs/jquery-cookie/1.4.1/jquery.cookie.js
curl -sS -o /dev/null -w 'fontawe  %{http_code}\n' https://maxcdn.bootstrapcdn.com/font-awesome/4.4.0/css/font-awesome.min.css
```

### Known-failing checks

These are expected to fail today. They are listed so that nobody reads their absence as success. [Block 04](../blocks/04-demo-quality-gate.md) owns them.

```bash
# HTTP should redirect. It currently returns 200 in plaintext.
curl -sS -o /dev/null -w 'http  %{http_code} %{redirect_url}\n' http://$HOST/

# Security headers should be present. They currently are not.
curl -sSI https://$HOST/ | grep -iE 'strict-transport|x-frame|x-content|referrer-policy'

# The server banner should not be disclosed. It currently reads `gunicorn`.
curl -sSI https://$HOST/ | grep -i '^server:'
```

Verified 15 Oct 2026: HTTP returns `200` with no redirect; no security header is present; `server: gunicorn` is disclosed.

## 2. Browser — the only check that proves the page works

**Cannot be scripted, and cannot be skipped.** Two defects in this project returned HTTP 200 for their entire lifetime: `/result` broke relative asset resolution, and the vote page's jQuery was blocked as mixed content. Section 1 passed throughout both.

| # | Check | Expected |
|---|---|---|
| 1 | Open `https://wtt-demo.syachin.de/` with DevTools Console and Network visible | Zero console errors. Zero failed or blocked requests. No mixed-content warning. |
| 2 | Console: `jQuery.fn.jquery` | `"3.7.1"`. Confirms the pinned library loaded and the two-major-version jump did not break the page. |
| 3 | Submit a vote | **On the POST response** the chosen option is disabled, shows a check icon, and the other option is at reduced opacity |
| 4 | Reload after voting | The highlight is **gone**. This is correct: the template renders the highlight only inside `{% if vote %}`, and `vote` is set only on POST. Not a defect. |
| 5 | Open `https://wtt-demo.syachin.de/result/` in a second tab, vote in the first | The count changes with no manual reload |
| 6 | Network tab on the result page | A Socket.IO connection to `/result/socket.io/` established, not failing or retrying |
| 7 | Address bar | Padlock present, no mixed-content indicator |

Record the browser, its version, the observer and the date. A human check written as though a script proved it is worse than no check.

Not yet recorded for the current `vote:9a9bb9e` image. That is the main outstanding item in Block 04.

## 3. Cluster

Requires `kubectl` access. **Not run when this document was written** — no AWS credentials were available in that session.

```bash
aws eks update-kubeconfig --region eu-north-1 --name wtt-demo-eks
```

### Nodes

```bash
kubectl get nodes -o wide
kubectl get node -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.allocatable.pods}{"\n"}{end}'
```

Expect two `Ready` nodes with no external address. The second command reports the real pod ceiling per node, which is what drove the `t3.large` choice; see [../lessons.md](../lessons.md).

### Workloads

```bash
kubectl -n vote-dev get pods -o wide
kubectl -n vote-dev get deploy,statefulset,svc
kubectl -n traefik get pods
kubectl -n cert-manager get pods
```

Expect five pods in `vote-dev`, all `Running`. Restart counts should be low and stable; a climbing count means a crash loop. Single replica each, so any restart is a brief outage of that function.

### Storage

```bash
kubectl -n vote-dev get pvc
PV=$(kubectl -n vote-dev get pvc data-postgres-0 -o jsonpath='{.spec.volumeName}')
kubectl get pv "$PV" -o custom-columns=\
'NAME:.metadata.name,SIZE:.spec.capacity.storage,RECLAIM:.spec.persistentVolumeReclaimPolicy,ZONE:.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0]'
```

Expect a bound 5 GiB claim. **Expect `RECLAIM` to read `Delete` today** — that is the data-loss risk owned by [Block 06](../blocks/06-data-durability.md). The zone column matters too: the PostgreSQL pod can only ever be scheduled where its volume lives.

### Gateway and routes

```bash
kubectl -n traefik get gateway traefik-gateway -o wide
kubectl get httproute -A
kubectl -n vote-dev describe httproute result | tail -25
```

Expect `PROGRAMMED: True` on the Gateway, and three routes in `vote-dev`. Each route should report `Accepted: True` and `ResolvedRefs: True`. A route attached to a listener it is not allowed on reports `NotAllowedByListeners`; a route naming a missing Service reports `ResolvedRefs: False`.

### Certificate

```bash
kubectl -n traefik get certificate
kubectl -n traefik describe certificate wtt-demo | tail -20
kubectl -n traefik get secret wtt-demo-tls -o jsonpath='{.metadata.name}{"\n"}'
```

Expect `wtt-demo` with `Ready=True` and `wtt-demo-staging` also present from the initial proving run. Nothing alerts on renewal failure, so this is worth checking by hand periodically.

### Secret shape, without revealing values

```bash
kubectl -n vote-dev get secret postgres-credentials \
  -o jsonpath='{range $k,$v := .data}{$k}{"\n"}{end}'
```

Expect exactly `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`. Never print the values. This has not been confirmed from the cluster; the application working is strong indirect evidence.

### Data path

```bash
# Queue depth. Should be at or near zero; a growing value means the worker is stuck.
kubectl -n vote-dev exec deploy/redis -- redis-cli LLEN votes

# Stored votes
kubectl -n vote-dev exec postgres-0 -- \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT vote, count(*) FROM votes GROUP BY vote ORDER BY vote"'
```

Note that because of defect D1 the `votes` table has no primary key, so a repeat vote from the same browser adds a row rather than replacing one. Totals can exceed the number of distinct voters. That is a known application defect, not a verification failure.

### No credential in any log

```bash
for d in vote result worker; do
  kubectl -n vote-dev logs deployment/$d --tail=200
done | grep -ciE 'password=|POSTGRES_PASSWORD'
```

Expect `0`. Both known leaks were fixed in Block 02; this check keeps them fixed.

## 4. AWS

Requires AWS credentials. **Not run when this document was written.**

```bash
aws eks describe-cluster --name wtt-demo-eks --region eu-north-1 \
  --query 'cluster.{status:status,version:version,endpointPublic:resourcesVpcConfig.endpointPublicAccess,cidrs:resourcesVpcConfig.publicAccessCidrs}'

# The NLB is owned by the Traefik Service, not by Terraform
aws elbv2 describe-load-balancers --region eu-north-1 \
  --query 'LoadBalancers[].{Name:LoadBalancerName,Type:Type,Scheme:Scheme,DNS:DNSName,State:State.Code}'

# Does DNS still point at the live load balancer?
aws route53 list-resource-record-sets --hosted-zone-id Z030020038RZDL2JLFT70 \
  --query "ResourceRecordSets[?Name=='wtt-demo.syachin.de.']"
```

The last check is important and easy to forget. The Route 53 alias target is **hardcoded** in `infra/terraform/iam/dns-demo.tf`. If the Traefik Service was ever recreated, AWS issued a new NLB and the record now points at one that no longer exists. Compare the `DNSName` from the second command with the alias target from the third; they must match. `terraform plan` will not catch a mismatch.

```bash
# Target health
TG=$(aws elbv2 describe-target-groups --region eu-north-1 \
      --query 'TargetGroups[0].TargetGroupArn' --output text)
aws elbv2 describe-target-health --target-group-arn "$TG" --region eu-north-1

# Pod Identity associations
aws eks list-pod-identity-associations --cluster-name wtt-demo-eks --region eu-north-1

# Nothing unexpected billing
aws ec2 describe-nat-gateways --region eu-north-1 \
  --filter Name=state,Values=available --query 'NatGateways[].NatGatewayId'
aws ec2 describe-volumes --region eu-north-1 \
  --query 'Volumes[].{Id:VolumeId,Size:Size,State:State}'
```

### Terraform describes reality

```bash
for r in network iam eks; do
  echo "== $r"
  (cd infra/terraform/$r && terraform plan -detailed-exitcode -var-file=../dev.tfvars 2>/dev/null \
    || cd infra/terraform/$r && terraform plan -detailed-exitcode)
done
```

Exit code `0` means no changes. `2` means drift between the code and the deployed infrastructure. An empty plan in all three roots is the real proof that the Terraform code describes what is running. **This has never been recorded.** Block 10 covers it.

## 5. Repository

No credentials needed.

```bash
python3 -m pytest tests/unit/test_repository_hygiene.py -v
```

Expect 12 passing tests. One of them, `test_infrastructure_code_is_not_ignored`, passes **vacuously**: it asserts on four paths that do not exist, and `git check-ignore` returns 1 for any non-ignored path whether or not it exists. Repair specified in [Block 04](../blocks/04-demo-quality-gate.md), item 04-D.

```bash
# No secret in the working tree
grep -rnEi 'aws_secret_access_key|BEGIN [A-Z ]*PRIVATE KEY' --include='*' . \
  --exclude-dir=.git --exclude-dir=.venv

# Every hostname occurrence, when adapting to another domain
grep -rn 'wtt-demo\.syachin\.de' infra/ k8s/

# Image tags in the manifests must match what is running
grep -n 'image:' k8s/apps/dev/applications.yaml
```

## Summary of what has and has not been verified

| Layer | State |
|---|---|
| Public HTTP behaviour, DNS, certificate, assets, Socket.IO | **Verified 15 Oct 2026**, externally, reproducible |
| HTTP redirect, security headers, server banner | **Verified absent** — Block 04 |
| Browser behaviour for the current `vote:9a9bb9e` image | **Not verified.** Requires an operator with a browser. |
| Cluster state: pods, Gateway, certificate, PVC, Secret keys | **Not verified** from this workstation |
| AWS state: cluster, NLB, DNS alias match, target health | **Not verified** from this workstation |
| Terraform plan empty | **Never recorded** — Block 10 |
| Clean-environment reproduction | **Never performed** — Block 10 |
| PostgreSQL restart persistence | **Operator-verified** in Block 02 |
| PVC deletion safety | **Not established.** No backup exists. — Block 06 |
