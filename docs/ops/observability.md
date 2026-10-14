# Observability

## What Is Collected

| Source | Collected by | Retention |
|---|---|---|
| Application metrics from `vote`, `result`, `worker` | Prometheus, through a `ServiceMonitor` per service | 7 days |
| Edge metrics from Traefik: request rate, latency, status codes per route | Prometheus, through a `ServiceMonitor` | 7 days |
| Certificate state from cert-manager | `kube-state-metrics` reading the `Certificate` resources | 7 days |
| Kubernetes object and node metrics | `kube-state-metrics` and `node-exporter`, part of `kube-prometheus-stack` | 7 days |
| Control plane logs | AWS CloudWatch, enabled by Terraform for `api`, `audit`, `authenticator` | 7 days |
| Container logs | Not aggregated. Read with `kubectl logs`. | The lifetime of the pod |

Container log aggregation is deliberately out of scope. Metrics and alerts answer the operational questions this system has, and a log stack would add cost and moving parts without changing any answer. If it is added later it goes in as Grafana Loki, as a stretch goal in Block 13.

Retention is 7 days because that is enough to investigate anything in a demonstration environment. It is a chosen number, not a default.

## Access

| Component | Address | Authentication |
|---|---|---|
| Grafana user interface | https://grafana.wtt-demo.syachin.de | Admin password from AWS Secrets Manager |
| Metrics HTTP API | The same host, through the Grafana data source proxy | A read-only service account token |
| Prometheus user interface | Not published. `kubectl -n observability port-forward svc/prometheus-operated 9090:9090` | Cluster access |
| Alertmanager | Not published. The same method, port 9093. | Cluster access |

Prometheus is not published directly. Its query API is reachable through Grafana, which means one authentication system instead of two, one certificate instead of two, and no second public endpoint to secure. Prometheus has no built-in authentication, so publishing it would require an extra proxy with its own credentials and its own failure modes. The reasoning is in [ADR 0009](../adr/0009-observability.md).

## Querying the Metrics API

Any PromQL expression can be run over HTTPS with the read-only token. This is the API access a reviewer needs.

```
TOKEN=<read-only service account token>
BASE=https://grafana.wtt-demo.syachin.de
PROXY=$BASE/api/datasources/proxy/uid/prometheus/api/v1

# Grafana health. No token needed.
curl -s $BASE/api/health | jq

# An instant query
curl -s -H "Authorization: Bearer $TOKEN" \
  --get --data-urlencode 'query=vote_queue_length' \
  $PROXY/query | jq '.data.result'

# A range query, the last hour at 1 minute resolution
curl -s -H "Authorization: Bearer $TOKEN" \
  --get \
  --data-urlencode 'query=rate(votes_processed_total[5m])' \
  --data-urlencode "start=$(date -u -d '1 hour ago' +%s)" \
  --data-urlencode "end=$(date -u +%s)" \
  --data-urlencode 'step=60' \
  $PROXY/query_range | jq '.data.result'

# Which targets are being scraped, and which are failing
curl -s -H "Authorization: Bearer $TOKEN" $PROXY/targets \
  | jq '.data.activeTargets[] | {job: .labels.job, health}'

# Which alerts are firing right now
curl -s -H "Authorization: Bearer $TOKEN" $PROXY/rules \
  | jq '.data.groups[].rules[] | select(.state=="firing") | {name: .name, since: .activeAt}'
```

The token has the Viewer role only. It can read metrics and dashboards and it cannot change anything. `test_grafana_token_cannot_write` in Block 10 proves that on every run.

How to obtain the token is described in [secrets.md](secrets.md).

## Useful Queries

The four questions that come up most often.

```
# Is the whole pipeline moving? Submitted minus processed should stay near zero.
rate(votes_submitted_total[5m]) - rate(votes_processed_total[5m])

# How deep is the queue? This is the single most useful number in the system.
vote_queue_length

# How fast is the result page answering?
histogram_quantile(0.95, rate(result_query_seconds_bucket[5m]))

# Is anything restarting?
increase(kube_pod_container_status_restarts_total{namespace="vote-prod"}[1h])

# How many days until the certificate expires?
(certmanager_certificate_expiration_timestamp_seconds - time()) / 86400

# What is the edge seeing, by route and status code?
sum by (code) (rate(traefik_service_requests_total[5m]))
```

`vote_queue_length` is the key signal. It sits exactly between the web tier and the database tier, so it rises whenever anything downstream is failing, regardless of the cause. The critical alert is built on it for that reason. A single number that catches many failures is worth more than ten alerts that each catch one.

## Dashboards

| Dashboard | Unique identifier | Shows |
|---|---|---|
| Application | `wtt-application` | Vote rate by option, queue depth, processing latency, error rate, result query latency, pod restarts |
| Platform | `wtt-platform` | Node capacity and pressure, pod phase by namespace, persistent volume usage, Spot interruptions, certificate expiry |

Both are provisioned from JSON in `deploy/observability/dashboards/`, through a ConfigMap. Nobody edits a dashboard in the user interface, because that change is not in Git and is lost on the next sync. To change a dashboard: export the JSON, commit it, let Argo CD apply it.

`test_dashboards_are_provisioned` checks that every panel returns data rather than "No data". A dashboard panel that has silently stopped working is worse than no panel, because it is trusted.

## Alerts

Every alert carries a `runbook_url` annotation pointing at the matching section of [runbooks.md](runbooks.md). An alert with no documented first step is noise, and `test_every_alert_has_a_runbook_url` makes that impossible to add.

Each alert's runbook section is named after the alert itself, so the `runbook_url` annotation points at a heading with the same name. `test_every_alert_has_a_runbook_section` reads the names out of the rule files and checks that the heading exists, which means a new alert cannot be added without a procedure.

| Alert | Condition | For | Severity | Runbook heading |
|---|---|---|---|---|
| `VoteServiceDown` | `up{job="vote"} == 0` | 2m | critical | `VoteServiceDown` |
| `ResultServiceDown` | `up{job="result"} == 0` | 2m | critical | `ResultServiceDown` |
| `WorkerNotProcessing` | `vote_queue_length > 50` | 5m | critical | `WorkerNotProcessing` |
| `VoteErrorRateHigh` | 5xx share above 5 percent | 5m | warning | `VoteErrorRateHigh` |
| `PostgresDown` | `up{job="postgres"} == 0` | 1m | critical | `PostgresDown` |
| `PostgresDiskFillingUp` | `predict_linear` fills within 24h | 10m | warning | `PostgresDiskFillingUp` |
| `BackupJobFailed` | No success in 26 hours | 0m | critical | `BackupJobFailed` |
| `CertificateRenewalFailed` | A `Certificate` has `Ready=False` | 1h | critical | `CertificateRenewalFailed` |
| `CertificateExpiringSoon` | Fewer than 14 days left on the served certificate | 1h | warning | `CertificateExpiringSoon` |
| `GatewayNotProgrammed` | The platform `Gateway` reports `Programmed=False` | 5m | critical | `GatewayNotProgrammed and TraefikDown` |
| `TraefikDown` | Fewer than 1 Traefik replica ready | 2m | critical | the same section |
| `NodeNotReady` | A node is not ready | 5m | warning | `NodeNotReady` |
| `PodCrashLooping` | More than 3 restarts in 15 minutes | 5m | warning | `PodCrashLooping` |

`CertificateRenewalFailed` is the one that matters for TLS, not `CertificateExpiringSoon`. cert-manager renews a 90-day Let's Encrypt certificate about 30 days before expiry, so a stuck renewal is detectable a month before a browser would ever complain. By the time the expiry alert fires, two thirds of that margin has already been spent. See [ADR 0016](../adr/0016-tls-with-cert-manager.md).

### Notification

Alerts are delivered by Alertmanager to a single webhook. For a demonstration environment, a chat or email webhook is enough and a paging service would be theatre. Critical alerts repeat every 4 hours, warnings every 24 hours, and both are grouped by alert name and namespace so that one incident produces one message.

Inhibition rules: `PostgresDown` suppresses `WorkerNotProcessing` and `ResultServiceDown`, because the database is the cause and the other two are symptoms. `TraefikDown` and `GatewayNotProgrammed` suppress `VoteServiceDown` and `ResultServiceDown`, because a broken edge makes every service look down from outside while the pods are healthy. Without those rules a single Traefik restart produces four messages and the reader has to work out which one matters.

## Scrape Configuration

| Job | Target | Port | Path | Interval |
|---|---|---|---|---|
| `traefik` | Service `traefik` in namespace `traefik` | 9100 | `/metrics` | 15s |
| `vote` | Service `vote` in both namespaces | 80 | `/metrics` | 15s |
| `result` | Service `result` in both namespaces | 80 | `/metrics` | 15s |
| `worker` | Service `worker` in both namespaces | 9090 | `/metrics` | 15s |
| `postgres` | `postgres-exporter` sidecar | 9187 | `/metrics` | 30s |
| `redis` | `redis-exporter` sidecar | 9121 | `/metrics` | 30s |

Every metric carries a `namespace` label, so one query distinguishes development from production. Alerts are restricted to `namespace="vote-prod"`, because a broken development environment is normal and must not wake anybody.

The network policies in Block 12 include an explicit rule allowing Prometheus to reach every metrics port, and a rule allowing the `traefik` namespace to reach `vote` and `result`. A default-deny policy added without the first rule makes every target disappear at once. Added without the second, it takes the whole site offline while every pod stays healthy, which looks like a gateway fault and is not. Both are the most common ways to break this setup.

## Verifying Observability Works

```
# Every application target is up
curl -s -H "Authorization: Bearer $TOKEN" $PROXY/targets \
  | jq '[.data.activeTargets[] | select(.health!="up")] | length'    # expect 0

# All six application metrics return data
for m in votes_submitted_total votes_processed_total votes_failed_total \
         vote_queue_length vote_processing_seconds_count result_query_seconds_count; do
  printf '%s: ' "$m"
  curl -s -H "Authorization: Bearer $TOKEN" --get --data-urlencode "query=$m" \
    $PROXY/query | jq -r '.data.result | length'
done

# Both dashboards exist
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/search?type=dash-db" \
  | jq -r '.[].uid'

# The rules are loaded
curl -s -H "Authorization: Bearer $TOKEN" $PROXY/rules \
  | jq '[.data.groups[].rules[]] | length'
```

The whole alerting path is proven once, for real, in Block 10: the worker is scaled to zero, votes are pushed, and `WorkerNotProcessing` is confirmed to reach the firing state. An alert rule that has never fired is an untested code path.
