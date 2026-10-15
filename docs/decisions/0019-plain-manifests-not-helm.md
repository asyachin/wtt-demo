# 0019 — Plain Kubernetes manifests instead of a Helm chart

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-15 |
| Deciders | Alexander Syachin |
| Block | 02 |
| Supersedes | The Helm umbrella chart specified by the original delivery plan |
| Superseded by | none |
| **Recorded** | **Retrospectively, 2026-10-15, reconstructed from commits `fa8f5e7`, `b940f96` and `50ef706`. The decision was made during implementation and was not written down at the time.** |

## Context

The original plan specified a Helm umbrella chart at `deploy/helm/wtt-vote/` with roughly eighteen templates, a `_helpers.tpl`, `values.yaml` plus `values-dev.yaml` and `values-prod.yaml`, and `helm unittest` cases. Block 02 wrote plain YAML under `k8s/` instead. No chart was ever created.

The plan's reasoning for a chart was the two-environment promotion model: one chart, two value files, with an automated test asserting that the two environments differed only in permitted keys.

That premise did not survive. Only one environment was deployed. `vote-prod` exists as an empty namespace and is not a production environment.

## Options

| Option | Advantage | Disadvantage |
|---|---|---|
| **Plain YAML in directories** | Readable as-is. No templating layer between the file and the cluster. `kubectl apply -f` and `kubectl diff -f` work directly. Argo CD adopts a directory as easily as a chart. | Values repeat across files. A second environment means copying or adding an overlay tool. |
| Helm umbrella chart | Parameterised per environment. Release history and `helm rollback`. The ecosystem default. | A templating layer. A rendering step before anything can be read. Roughly 18 templates and a values schema for 16 objects. Justified by a second environment that does not exist. |
| Kustomize | Overlays with no templating. Patches are reviewable. | Another tool. Base-plus-overlay indirection for one environment. |

## Decision

Plain Kubernetes manifests, organised by lifecycle rather than by service:

```
k8s/
├── base/                     changes rarely, foundational
│   ├── namespaces.yaml
│   ├── storage/gp3.yaml
│   ├── postgres/{statefulset,service}.yaml
│   └── redis/{deployment,service}.yaml
├── apps/dev/                 changes with every release
│   ├── applications.yaml     vote, result, worker: Deployments and Services
│   ├── httproutes.yaml
│   └── result-redirect.yaml
└── platform/                 cluster services
    ├── traefik/{values,values-public}.yaml      Helm values, not manifests
    └── cert-manager/{clusterissuer,certificate}-{staging,production}.yaml
```

Applied with `kubectl apply -f`. Traefik and cert-manager remain Helm releases installed by hand; only their configuration objects live here.

## Reasoning

**The justification for a chart was a second environment, and there is one environment.** A chart with a single values file is a templating layer with nothing to parameterise. The plan's most valuable chart-related test, which asserted that dev and prod differed only in permitted keys, has nothing to compare.

**Readability matters more than reuse at this size.** Sixteen objects. `k8s/base/postgres/statefulset.yaml` can be read and understood without rendering it first. For a project whose purpose is to demonstrate understanding to a reviewer, a file that says what it does beats a template that must be executed to be read.

**`kubectl diff -f` works directly.** Comparing a file against the cluster needs no `helm template` step, which mattered for adopting the running application into Argo CD — see [../roadmap.md](../roadmap.md), Block 05 — where the method was to prove an empty diff before syncing.

**Argo CD treats a directory as a first-class source.** Choosing plain YAML costs nothing in the GitOps plan.

**Directory layout encodes change frequency.** `base/` holds namespaces, storage and data services, which change rarely. `apps/dev/` holds the three application workloads and their routes, which change on every release. That split makes the blast radius of a change visible from its path, and it maps directly onto the separate Argo CD Applications planned in Block 05.

**Helm is still used where it belongs.** Traefik and cert-manager are third-party components with genuine configuration surface and upstream-maintained charts. Writing their manifests by hand would be worse. The distinction is: Helm for third-party software, plain YAML for our own sixteen objects.

## Consequences

### Positive

- Every manifest is readable without a rendering step.
- `kubectl diff -f` and `kubectl apply -f` work directly, which simplifies Argo CD adoption.
- No templating syntax, no `_helpers.tpl`, no values schema to learn or maintain.
- Directory structure communicates change frequency and maps onto the planned Argo CD Applications.
- Nothing is lost for GitOps.

### Negative

- **A second environment has no clean path.** Adding `vote-prod` means copying `apps/dev/` and maintaining two near-identical trees, or introducing Kustomize. This is the real cost, and it is the direct consequence of dropping the chart. It will have to be paid if the promotion model is ever built.
- **Values repeat.** The image registry prefix, the namespace and resource limits appear in several places. The hostname `wtt-demo.syachin.de` appears in all three route files and in the Traefik values. Changing it means a `grep`, not a value edit.
- **No `helm rollback`.** Reverting a release is `git checkout <commit> -- <file>` followed by `kubectl apply`. Adequate, but it depends on Git discipline rather than on release history stored in the cluster. Block 05 replaces it with `git revert` plus a sync.
- **No release metadata in the cluster.** Nothing records which commit produced the running state. The image tag is the only link, and it works because tags are commit SHAs — but it only covers the three application images, not the manifests around them.
- **No schema validation.** A chart could validate values. Nothing here catches a malformed manifest before `kubectl` rejects it, and with no CI nothing catches it before it reaches the cluster.
- **`applications.yaml` holds six objects in one file.** Convenient for applying, but it means a change to the `vote` Deployment and a change to the `result` Service touch the same file, which obscures blame and widens merge conflicts.

### Neutral

- The planned chart tests — `helm lint`, `kubeconform`, `helm unittest` — do not exist. Nor do they exist for the plain YAML. Manifest validation is absent either way and is CI work, Block 07.

## Verification

```bash
# No Helm chart exists for the application
ls deploy/ 2>/dev/null || echo "no deploy/ directory"
find k8s -name 'Chart.yaml' -o -name 'values.yaml' -path '*wtt*' || echo "no chart"

# Every manifest is valid and server-side acceptable
kubectl apply --dry-run=server -f k8s/base/ -f k8s/apps/dev/

# Files match the cluster
kubectl diff -f k8s/apps/dev/ || true

# Helm is used only for third-party components
helm list -A
```

`helm list -A` should show `traefik` and `cert-manager`, and nothing for the application. The `kubectl` checks need cluster access and have not been recorded.

## Revisit when

A second environment is actually built, which is the condition under which the original reasoning for a chart becomes valid again. At that point Kustomize is the lighter answer: overlays give per-environment differences without a templating language, and the base stays readable.

Also revisit if the manifest count grows substantially. Sixteen objects is comfortable; sixty would not be.
