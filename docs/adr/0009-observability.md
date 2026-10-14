# 0009 — Publish Grafana Only, and Reach Prometheus Through It

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | none |

## Context

The requirement is that Grafana and Prometheus are reachable over an HTTP API, so that a reviewer can query the metrics of a live system during an interview rather than being shown a screenshot.

Prometheus has no authentication and no authorisation. None. Publishing it means publishing an unauthenticated query interface, which also exposes `/api/v1/admin` endpoints unless they are disabled, and `/-/reload`.

Grafana has user accounts, service accounts with scoped tokens, and a role model.

The ingress layer is an AWS ALB, which has no basic authentication feature. Its only built-in authentication is OpenID Connect or Amazon Cognito.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| Publish Grafana, reach Prometheus through its data source proxy | One public component, one authentication system, one certificate, scoped tokens. Full PromQL over HTTP. | The query path goes through Grafana, so a Grafana outage removes API access as well |
| Publish both, with basic authentication on Prometheus | Direct access to the Prometheus API | The ALB cannot do basic authentication, so it needs a second ingress controller or an oauth2-proxy. Two public surfaces, two credentials. |
| Publish both, Prometheus unauthenticated | Simplest | An open query interface on the internet. It leaks the internal topology, and a crafted query can exhaust memory. Unacceptable. |
| Publish neither, use `kubectl port-forward` | Most secure | A reviewer with no cluster access sees nothing, which fails the requirement |
| Put Prometheus behind ALB OpenID Connect authentication | Strong, native | Needs an identity provider or Cognito. Disproportionate, and a reviewer cannot use it with `curl`. |

## Decision

Grafana is published at `grafana.wtt-demo.syachin.de`. Prometheus is not published.

The Prometheus query API is reached through the Grafana data source proxy, with a read-only service account token:

```
GET https://grafana.wtt-demo.syachin.de/api/datasources/proxy/uid/prometheus/api/v1/query?query=<promql>
Authorization: Bearer <token>
```

The token has the Viewer role and nothing else. Grafana's own `/api/health` is open, with no token.

Prometheus and Alertmanager user interfaces are reached by `kubectl port-forward`.

## Reasoning

This satisfies the requirement with one public component instead of two. The full Prometheus query and range query API, the targets endpoint, and the rules endpoint are all reachable through the proxy, so nothing about the capability is lost. The only thing lost is the Prometheus user interface over the internet, and the Grafana Explore view is a better one anyway.

One public component means one certificate, one ingress rule, one authentication system, and one thing to patch. Two would mean adding either a second ingress controller or an oauth2-proxy purely to put a password in front of Prometheus, which is a new deployment, a new secret, and a new failure mode, to protect something that is already protected by not being published.

The token being read-only is the part that must be true and not merely intended. A token handed to a stranger that can create a dashboard, edit a data source, or change an alert rule is not read-only. `test_grafana_token_cannot_write` asserts a 403 on a dashboard creation attempt, which is the kind of check that is obvious in hindsight and is usually missing.

Leaving `/api/health` open is deliberate. It lets an automated end-to-end check confirm that Grafana is alive without holding a credential, and it reveals only a version string.

## Consequences

### Positive

- One public endpoint for all observability, with one certificate.
- Prometheus is never exposed to the internet, so its lack of authentication stops being a problem.
- Scoped, revocable tokens instead of a shared password.
- A reviewer can run any PromQL query with `curl` and one bearer token.
- No additional ingress controller and no oauth2-proxy.

### Negative

- Grafana is a single point of failure for API access. If Grafana is down, metrics cannot be queried remotely even though Prometheus is collecting them. During a Grafana outage the fallback is `kubectl port-forward`, which needs cluster access.
- The proxy path is longer and less familiar than `prometheus.example.com/api/v1/query`. It has to be documented, which it is, with working commands.
- The data source unique identifier appears in the URL, so it is pinned to `prometheus` in the chart values. Letting it be generated would break every documented command on reinstall.
- Alertmanager is not reachable remotely at all. Firing alerts can be read through the proxy's `/rules` endpoint, but silencing one needs cluster access. Acceptable for a demonstration.
- A token in a shell history or a chat message is a leaked credential. The rotation procedure exists for that reason.

### Neutral

- Metric retention is 7 days on a 20 GiB volume. Enough to investigate anything in this environment, and a chosen number rather than a default.
- Container log aggregation is out of scope. Metrics and alerts answer every operational question this system has, and Loki would add cost and components without changing an answer.

## Verification

- `test_grafana_api_health` in Block 10, over HTTPS.
- `test_grafana_token_can_query_prometheus` in Block 10, which runs a real query through the proxy.
- `test_grafana_token_cannot_write` in Block 10, which requires a 403.
- `test_all_application_targets_are_up` and `test_application_metrics_are_present` in Block 10.
- `test_worker_down_fires_an_alert` in Block 10, which proves the alerting path by breaking the system on purpose.
- The working commands in `docs/ops/observability.md`, which are run against the live system before the block closes.

## Revisit When

Someone needs to silence an alert remotely, or Grafana's availability becomes the limiting factor for diagnosing an incident. Either one justifies exposing Alertmanager and Prometheus behind a proper authenticating proxy.
