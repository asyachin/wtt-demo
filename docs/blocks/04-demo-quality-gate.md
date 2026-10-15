# Block 04 — Public Demo Quality Gate

| Field | Value |
|---|---|
| Status | **`IN PROGRESS`** |
| Branch | `block/04-demo-quality-gate` |
| Depends on | Block 03 |
| Next | Block 05 |
| Report type | Written before the remaining implementation. Part of the scope is already deployed; that part is reported as evidence. |

## Goal

Make the public demonstration correct in a browser, not merely correct by HTTP status code.

Block 03 closed with every status check passing while two browser-level defects were live: `/result` broke relative asset resolution, and the vote page loaded jQuery over plain `http://`, which browsers block on an HTTPS page. Neither was visible to a status-code check. This block exists because of that gap, and its acceptance criteria are written so the same class of defect cannot pass again.

## Scope

| ID | Item | State |
|---|---|---|
| 04-A | Remove blocked active content from the vote page | **Done, verification outstanding** |
| 04-B | Redirect HTTP to HTTPS | **Not started** |
| 04-C | Browser security response headers | **Not started** |
| 04-D | Repair the defective repository hygiene test | **Not started** |
| 04-E | Automate the mixed-content check so it cannot regress | **Not started** |

## Out of scope

| Item | Owner |
|---|---|
| PostgreSQL volume reclaim policy, backup and restore | [Block 06](06-data-durability.md) |
| Argo CD and GitOps adoption | [Block 05](05-gitops.md) |
| CI pipeline, image signing, vulnerability scanning | Block 07 |
| Non-root containers, Pod Security Standards, NetworkPolicy, pinned dependencies, health and metrics endpoints | Block 09 |
| Defects D1, D2, D4, D12, D13 | Deferred, see [../roadmap.md](../roadmap.md#deferred-beyond-the-interview) |
| Vendoring third-party JavaScript into the image | Optional later improvement, see 04-A |
| Proxy Protocol v2 | Deferred |

## Prerequisites

- Block 03 `CLOSED`.
- Cluster access, and the ability to build and push to `ghcr.io/asyachin/wtt-demo`.
- A browser with developer tools, for the criteria that only a human can satisfy.

---

## 04-A — Blocked active content

### Observed implementation

| Commit | Subject |
|---|---|
| `9a9bb9e` | `fix(vote): load pinned jQuery over HTTPS` |
| `a4d979f` | `deploy(vote): release HTTPS asset fix image 9a9bb9e` |

`9a9bb9e` changed one line in `app/vote/templates/index.html`:

```diff
-    <script src="http://code.jquery.com/jquery-latest.min.js" type="text/javascript"></script>
+    <script src="https://code.jquery.com/jquery-3.7.1.min.js" type="text/javascript"></script>
```

`a4d979f` updated `k8s/apps/dev/applications.yaml` from `vote:f0ea1a0` to `vote:9a9bb9e`. The image was built, pushed and rolled out.

This also replaced the frozen `jquery-latest` alias, which jQuery's CDN pins at 1.11, with an explicitly pinned 3.7.1. That is an improvement in reproducibility and a two-major-version jump at the same time.

**The implementation technique is not prescribed.** Loading a pinned library over HTTPS from a CDN satisfies this block. Vendoring the files into the image would remove the external runtime dependency and is a reasonable later improvement, but it is not required here. The criteria below test the outcome, not the technique.

### Evidence recorded 15 October 2026

Verified externally, from a workstation outside AWS:

```
$ curl -sS https://wtt-demo.syachin.de/ | grep -E 'script src|link rel="stylesheet"'
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/font-awesome/4.4.0/css/font-awesome.min.css">
    <script src="https://code.jquery.com/jquery-3.7.1.min.js" type="text/javascript"></script>
    <script src="//cdnjs.cloudflare.com/ajax/libs/jquery-cookie/1.4.1/jquery.cookie.js"></script>

$ curl -sS -o /dev/null -w '%{http_code}' https://code.jquery.com/jquery-3.7.1.min.js
200
$ curl -sS -o /dev/null -w '%{http_code}' https://cdnjs.cloudflare.com/ajax/libs/jquery-cookie/1.4.1/jquery.cookie.js
200
```

No `http://` reference remains in the served HTML. The blocked-content condition is resolved at source level.

### Two findings from that output

**The remaining protocol-relative reference is not mixed content.** `//cdnjs.cloudflare.com/...` resolves to HTTPS on an HTTPS page, so no browser blocks it. It is a legacy pattern and an external runtime dependency, tracked as defect D5b, not as a blocker for this block.

**That plugin is never used.** `jquery.cookie` is loaded on every page view, and nothing calls `$.cookie`. The `voter_id` cookie is set server-side by Flask with `resp.set_cookie`. The script tag can simply be deleted. Optional within this block.

### A correction to the criteria

The first draft of this block required that, after voting, the chosen option remains highlighted **after a page reload**. Reading `app/vote/app.py` shows that is impossible by design:

```python
vote = None
if request.method == "POST":
    vote = request.form["vote"]
```

The template renders the highlighting script only inside `{% if vote %}`, so it appears on the POST response and never on a subsequent GET. A criterion written against a reload would fail permanently against correct behaviour. Criterion 3 below is written against the POST response instead.

---

## 04-B — HTTP to HTTPS redirect

### Current state

All three `HTTPRoute` objects attach to both Gateway listeners:

```yaml
parentRefs:
  - { name: traefik-gateway, namespace: traefik, sectionName: web }        # :8000 HTTP
  - { name: traefik-gateway, namespace: traefik, sectionName: websecure }  # :8443 HTTPS
```

No route carries a redirect filter, so a request on port 80 is answered in plaintext. Confirmed externally: `http://wtt-demo.syachin.de/` returns 200.

### Target design

Two listeners already exist, which is what makes this solvable. The NLB operates at layer 4 and adds no `X-Forwarded-Proto`, so a single entrypoint could not distinguish the schemes and a redirect rule on it would loop. Separate listeners avoid that entirely.

1. **A new `HTTPRoute` attached only to the `web` listener**, redirecting everything:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: https-redirect
  namespace: vote-dev
spec:
  hostnames: [wtt-demo.syachin.de]
  parentRefs:
    - name: traefik-gateway
      namespace: traefik
      sectionName: web          # HTTP listener only
  rules:
    - matches:
        - path: { type: PathPrefix, value: / }
      filters:
        - type: RequestRedirect
          requestRedirect:
            scheme: https
            statusCode: 301
```

`scheme: https` with no `path` and no `hostname` preserves the request path. The Gateway API specification does not modify the query string on a redirect, so queries are preserved; criterion 7 verifies that rather than assuming it.

2. **Remove `sectionName: web`** from the `parentRefs` of `vote`, `result` and `result-redirect`, leaving them on `websecure` only.

No ACME exemption is needed. Certificates use DNS-01, so issuance and renewal never require inbound HTTP. This is a direct benefit of the Block 03 design.

### Order of application, and why it matters

Apply in this order, verifying after each step:

| Step | Action | Effect | Risk |
|---|---|---|---|
| 1 | Apply `https-redirect` | None yet. On the `web` listener, `vote` also matches `PathPrefix /`, and Gateway API breaks a specificity tie in favour of the older route, so HTTP keeps serving the page. | None |
| 2 | Remove `web` from `result` and `result-redirect` | `/result` paths on HTTP now fall to `https-redirect` | Low |
| 3 | Remove `web` from `vote` | `/` on HTTP now redirects. Target state reached. | Low |

Applying step 3 first would leave HTTP with no matching route for `/` and return 404 until step 1 landed. Starting with the inert change means every intermediate state is serviceable.

HTTPS traffic is untouched throughout, because no change is made to the `websecure` listener or to the routes' HTTPS attachment.

### Validation after each step

```bash
# HTTPS must be unaffected at every step
curl -sS -o /dev/null -w 'https /        %{http_code}\n' https://wtt-demo.syachin.de/
curl -sS -o /dev/null -w 'https /result  %{http_code} %{redirect_url}\n' https://wtt-demo.syachin.de/result
curl -sS -o /dev/null -w 'https /result/ %{http_code}\n' https://wtt-demo.syachin.de/result/
curl -sS -o /dev/null -w 'socket.io      %{http_code}\n' \
  'https://wtt-demo.syachin.de/result/socket.io/?EIO=4&transport=polling'

# HTTP behaviour changes as steps land
curl -sS -o /dev/null -w 'http  /        %{http_code} %{redirect_url}\n' http://wtt-demo.syachin.de/

# Route attachment status
kubectl get httproute -A
kubectl -n vote-dev describe httproute https-redirect | tail -20
```

### Rollback

The change is three small manifest edits and `kubectl apply` is idempotent, so rollback is restoring the previous file and re-applying:

```bash
git checkout HEAD -- k8s/apps/dev/httproutes.yaml k8s/apps/dev/result-redirect.yaml
kubectl apply -f k8s/apps/dev/httproutes.yaml -f k8s/apps/dev/result-redirect.yaml
kubectl delete httproute https-redirect -n vote-dev     # only if step 1 is being undone
```

Recovery is a few seconds. Nothing in this change touches a Deployment, a volume, a Secret or the certificate, so there is no data risk and no pod restart. Note that there is no GitOps revert path yet; until Block 05, rollback is a manual `kubectl apply`.

---

## 04-C — Security response headers

**Not implemented. Absent from the live system**, confirmed externally: no `Strict-Transport-Security`, no `X-Frame-Options`, no `X-Content-Type-Options`, and `server: gunicorn` is disclosed.

### Target design

A `ResponseHeaderModifier` filter on the routes attached to the `websecure` listener:

```yaml
filters:
  - type: ResponseHeaderModifier
    responseHeaderModifier:
      set:
        - { name: Strict-Transport-Security, value: "max-age=31536000; includeSubDomains" }
        - { name: X-Content-Type-Options, value: nosniff }
        - { name: X-Frame-Options, value: DENY }
        - { name: Referrer-Policy, value: strict-origin-when-cross-origin }
      remove: [Server]
```

Placing the filter only on the HTTPS routes means HSTS is never sent on a plaintext response, which is what the specification requires. Criterion 9 verifies that.

`max-age` starts at one year without `preload`. `preload` submits the domain to a browser-maintained list and is effectively irreversible, which is not appropriate for a demonstration.

**Implementation risk.** `ResponseHeaderModifier` is an Extended-conformance feature of the Gateway API. Traefik v3 is expected to support it, but that has not been confirmed against chart `41.7.1` in this cluster. If it is unsupported, the route will report a condition explaining why, and the fallback is to set the headers in the applications themselves — which would be three code changes across three languages and therefore a different block. Verify support before planning the work:

```bash
kubectl -n vote-dev describe httproute vote | tail -20
```

---

## 04-D — Repair the defective hygiene test

`tests/unit/test_repository_hygiene.py::test_infrastructure_code_is_not_ignored` asserts that `git check-ignore` returns 1 for four paths:

```
infra/terraform/env/platform/main.tf
infra/terraform/env/platform/terraform.tfvars
infra/terraform/env/platform/.terraform.lock.hcl
deploy/helm/wtt-vote/values-prod.yaml
```

None exists. The original plan expected one Terraform root at `env/platform` and a Helm chart at `deploy/helm/wtt-vote`; Block 01 used four roots and no chart was ever created. `git check-ignore` returns 1 for any path that is not ignored, existing or not, so **the test passes without checking anything and cannot fail.**

### Required repair

1. Replace the four paths with paths that exist in this repository, for example `infra/terraform/eks/main.tf`, `infra/terraform/dev.tfvars`, `infra/terraform/eks/.terraform.lock.hcl`, `k8s/apps/dev/applications.yaml`.
2. Assert that each path **exists** as well as being un-ignored. The existence assertion is what makes the test non-vacuous: a renamed or deleted file now fails instead of passing silently.
3. Demonstrate that the repaired test can fail. Temporarily add a pattern to `.gitignore` that matches one of the paths, run the test, observe the failure, then revert. Record the observed failure output in the Evidence section. A test that has never failed has not been shown to test anything.

---

## 04-E — Automate the mixed-content check

Mixed content was live for the whole of Block 03 and no automated check would have caught it. It can be detected mechanically, without a browser: extract every `src` and `href` from the served HTML and assert that none begins with `http://`.

A test in `tests/e2e/` under the existing `e2e` marker, taking a base URL so it can run against the live site or a port-forward. The `e2e` marker is already declared in `pyproject.toml` and currently has no tests.

This catches the blocked-content class of defect permanently. It does not replace the browser criteria — it cannot detect a JavaScript error — which is why both exist.

---

## Acceptance criteria

| # | Criterion | Verification | Expected | State |
|---|---|---|---|---|
| 1 | No page references a resource over plain `http://` | `curl -sS <url> \| grep -oE '(src\|href)="[^"]+"'` for `/` and `/result/` | Zero matches beginning `http://` | **Met** 15 Oct 2026 |
| 2 | Every referenced external asset resolves | `curl -o /dev/null -w '%{http_code}'` per extracted URL | All 200 | **Met** 15 Oct 2026 |
| 3 | **The vote page works in a browser, console clean** | Operator opens `https://wtt-demo.syachin.de/` with DevTools Console and Network open, submits a vote | Zero console errors; zero blocked or failed requests; on the POST response the chosen option is disabled, shows a check icon, and the other option is at reduced opacity. **Not after a reload — see 04-A.** Record browser and version. | **Outstanding** |
| 4 | **The result page updates live in a browser** | Operator opens `https://wtt-demo.syachin.de/result/` in a second tab and votes in the first | The count changes with no manual reload, and the console shows an established Socket.IO connection | **Outstanding** |
| 5 | jQuery 3.7.1 is loaded and functional | Browser console: `typeof jQuery`, `jQuery.fn.jquery` | `"function"` and `"3.7.1"`. Confirms the two-major-version jump did not break the inline script, defect D5a. | **Outstanding** |
| 6 | HTTP is redirected, not served | `curl -o /dev/null -w '%{http_code} %{redirect_url}' http://wtt-demo.syachin.de/` | `301`, location `https://wtt-demo.syachin.de/` | **Not started** |
| 7 | The redirect preserves path and query | Same against `http://wtt-demo.syachin.de/result/?x=1` | `301` to the identical HTTPS path and query | **Not started** |
| 8 | Security headers present on HTTPS | `curl -sSI https://wtt-demo.syachin.de/` | `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` all present | **Not started** |
| 9 | HSTS is not sent over plain HTTP | `curl -sSI http://wtt-demo.syachin.de/` | No `Strict-Transport-Security` on the redirect response | **Not started** |
| 10 | The server banner is not disclosed | `curl -sSI https://wtt-demo.syachin.de/ \| grep -i '^server:'` | Absent or non-identifying. Currently `server: gunicorn`. | **Not started** |
| 11 | All routing behaviour still correct after every change | [../operations/verify.md](../operations/verify.md) section 1 | `/` 200, `/result` 301 to `/result/`, `/result/` 200, `/result/app.js` 200, socket.io 200 | **Re-run after each step** |
| 12 | Certificate still valid and trusted | `openssl s_client` as in section 1 | Let's Encrypt production, correct name, unexpired | **Re-run after each step** |
| 13 | The repaired hygiene test validates existing paths and can fail | Run it; then plant a matching `.gitignore` pattern, observe failure, revert | Passes normally, fails on the planted case. Record both outputs. | **Not started** |
| 14 | The mixed-content check runs as a test | `python3 -m pytest -m e2e` | Passes, and fails if an `http://` reference is reintroduced | **Not started** |
| 15 | Running image recorded | `kubectl -n vote-dev get deploy vote -o jsonpath='{..image}'` | `ghcr.io/asyachin/wtt-demo/vote:9a9bb9e`, matching `a4d979f` | **Outstanding** — needs cluster access |

Criteria 3, 4 and 5 are the ones that distinguish this block from Block 03. They cannot be satisfied by a script, and they must not be marked met without a named observer and a date.

## Evidence

### Recorded

| Item | Evidence |
|---|---|
| 04-A source change | `9a9bb9e`, one line in `app/vote/templates/index.html` |
| 04-A image build and push | `ghcr.io/asyachin/wtt-demo/vote:9a9bb9e`, reported built and pushed by the operator |
| 04-A deployment | `a4d979f` updated `k8s/apps/dev/applications.yaml`; rolling update reported completed by the operator |
| Criterion 1 | Served HTML contains no `http://` reference. Verified externally 15 Oct 2026, output above. |
| Criterion 2 | Both external assets return 200 over HTTPS. Verified externally 15 Oct 2026. |
| Criterion 11 baseline | `/` 200, `/result` 301 to `/result/`, `/result/` 200, `/result/app.js` 200, socket.io 200. Verified externally 15 Oct 2026. |
| Criterion 12 baseline | `CN=wtt-demo.syachin.de`, issuer `C=US, O=Let's Encrypt, CN=YR2`, valid 2026-10-14 to 2027-01-12. Verified externally 15 Oct 2026. |

### Outstanding

| Item | Why |
|---|---|
| Criteria 3, 4, 5 | Require a browser and a human observer |
| Criterion 15 | Requires cluster access, unavailable when this report was written |
| Criteria 6 to 10, 13, 14 | Work not started |

## Deviations from plan

Recorded as the block proceeds.

| Deviation | Reason |
|---|---|
| Mixed content fixed by pinning the CDN library over HTTPS rather than vendoring it into the image | Smaller change, one line, no build-context or `.dockerignore` implications. Removes the blocked-content defect, which is what the criterion requires. Vendoring remains available as a later improvement and would also remove the external runtime dependency. |
| Criterion on the voted-state highlight rewritten from "after reload" to "on the POST response" | The application sets `vote` only on POST, so the original criterion was unsatisfiable against correct behaviour. Found by reading the source. See [../lessons.md](../lessons.md). |

## Risks and limitations after this block

Even when fully closed:

- The vote page still depends on two third-party CDNs at runtime, `code.jquery.com` and `cdnjs.cloudflare.com`. A CDN outage degrades the page.
- `jquery.cookie` is still loaded and still unused, defect D5b.
- Containers still run as root; Python dependencies remain unpinned; no health or metrics endpoints exist.
- Still no backup for PostgreSQL. The reclaim policy risk is untouched; [Block 06](06-data-durability.md).
- Traefik still runs a single replica with no PodDisruptionBudget.
- Still no monitoring, so a certificate renewal failure would go unnoticed until expiry.

## Definition of Done

- [ ] Criteria 1 and 2 met — **already met**
- [ ] Criteria 3, 4, 5 met, with browser, version, observer and date recorded
- [ ] Criteria 6 and 7 met: HTTP redirects, preserving path and query
- [ ] Criteria 8, 9, 10 met, or `ResponseHeaderModifier` confirmed unsupported and the limitation recorded with its fallback
- [ ] Criterion 13 met: the repaired test validates real paths and its failure has been observed
- [ ] Criterion 14 met: the mixed-content check runs under `pytest -m e2e`
- [ ] Criteria 11 and 12 re-verified after the final change
- [ ] Criterion 15 recorded
- [ ] No secret added to the repository
- [ ] Documentation updated per [../process.md](../process.md#documentation-update-at-block-closure)
- [ ] Branch merged into `dev`
- [ ] Status set to `CLOSED` here and in [../roadmap.md](../roadmap.md)
