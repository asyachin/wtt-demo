# Rebuild from a clean environment

How to build this platform in a fresh AWS account. Commands match the repository at `390a119`.

> **A documented procedure, not a verified one.** It was written by reading the Terraform roots, the manifests and the Git history. **A clean-environment rebuild has never been performed.** Block 10 exists to run it and correct whatever is wrong. Expect gaps, particularly in the steps marked MANUAL.

## Steps that are not automated

| Step | Why it is manual |
|---|---|
| Gateway API CRDs | `kubectl apply` of a release manifest |
| Traefik | Helm release. The original install command was not captured; the one below is reconstructed from the committed values files. |
| cert-manager | Helm release from an OCI registry |
| Argo CD | Helm release |
| `postgres-credentials` Secret | Created by the operator. Deliberately never in Git. |
| Traefik subnet IDs | Hardcoded in `k8s/platform/traefik/values-public.yaml`. A new account means new IDs. |
| Route 53 alias target | The load balancer hostname is hardcoded in `infra/terraform/iam/dns-demo.tf`. Kubernetes generates it, so it cannot be known before Traefik is installed. Two-stage procedure in step 3. |
| Route 53 hosted zone | Pre-existing. Not created by this project. |
| Operator address allowlist | `api_public_access_cidrs` has no default and must be supplied. |
| HTTPRoutes, `k8s/base`, cert-manager objects | Applied with `kubectl`. Argo CD manages only the application Deployments and Services. |

### Component versions

From the installation history of the deployed cluster. Pin these on a rebuild.

| Component | Version | Source |
|---|---|---|
| Gateway API CRDs | `v1.6.1`, Standard channel | `github.com/kubernetes-sigs/gateway-api` release manifest |
| cert-manager | chart `v1.21.2` | `oci://quay.io/jetstack/charts/cert-manager` |
| Traefik | chart `41.7.1` | `https://traefik.github.io/charts` |
| Argo CD | see `k8s/platform/argocd/values.yaml` | `https://argoproj.github.io/argo-helm` |

These live in this document, not in code, so nothing enforces them. Re-verification commands are given in each step.

## Operator input required

No default exists for these. Substitute your own values.

| Value | Current | Where |
|---|---|---|
| AWS account ID | `899088266068` | `infra/terraform/dev.tfvars`, variable defaults in `iam` and `eks`, `allowed_account_ids` in every `versions.tf` |
| State bucket | `wtt-demo-tfstate-899088266068-eu-north-1` | `bootstrap/bootstrap.tfvars` and the backend block of all four roots |
| Region | `eu-north-1` | throughout |
| Hosted zone ID | `Z030020038RZDL2JLFT70` | `iam/cert-manager.tf`, `iam/dns-demo.tf`, both `ClusterIssuer` manifests |
| Public hostname | `wtt-demo.syachin.de` | Terraform, Traefik values, both issuers, both certificates, all four `HTTPRoute` objects |
| ACME contact email | in both `ClusterIssuer` manifests | `k8s/platform/cert-manager/` |
| Operator address CIDRs | none | `api_public_access_cidrs` |
| Public subnet IDs | two values | `k8s/platform/traefik/values-public.yaml` |
| Load balancer hostname | one value | `iam/dns-demo.tf` |
| Repository URL | `https://github.com/asyachin/wtt-demo.git` | `k8s/platform/argocd/*.yaml` |
| PostgreSQL credentials | not in Git | the `postgres-credentials` Secret |

The backend `bucket` cannot come from a variable — Terraform requires literal backend configuration. Edit the four files, or pass `-backend-config`.

The hostname appears in about ten places and is not parameterised. Grep rather than trusting the list:

```bash
grep -rn 'wtt-demo\.syachin\.de' infra/ k8s/
```

## Prerequisites

| Tool | Required |
|---|---|
| `terraform` | `>= 1.16.0, < 1.17.0`, enforced by every root |
| `aws` CLI | v2, with credentials able to create VPC, IAM, EKS and S3 resources |
| `kubectl` | 1.33 or later for a 1.36 cluster |
| `helm` | 3.x |
| `git`, `curl`, `dig`, `openssl` | any recent |
| `python3` | 3.11+, for the test suite and helper scripts |
| `docker` | only to build images locally; CI does this normally |

The AWS provider is pinned to exactly `6.68.0` and lock files are committed, so run `terraform init` without `-upgrade`.

## 1. AWS account

```bash
aws sts get-caller-identity          # confirm the account matches the configuration
export AWS_REGION=eu-north-1
aws route53 list-hosted-zones --query 'HostedZones[].{Id:Id,Name:Name}' --output table
```

A public hosted zone must already exist for the parent domain, with name servers delegated. This project creates a record inside an existing zone.

## 2. Terraform state backend

Run once. Uses local state, because it creates the bucket that backs everything else.

```bash
cd infra/terraform/bootstrap
terraform init
terraform apply -var-file=bootstrap.tfvars
```

Creates a versioned, AES256-encrypted, private bucket with `BucketOwnerEnforced` and `prevent_destroy`. Locking is native S3 `use_lockfile`; there is no DynamoDB table.

## 3. Terraform roots

Order is mandatory. `eks` reads `network` and `iam` through `terraform_remote_state`.

```
bootstrap  →  network  →  iam (stage A)  →  eks  →  …  →  iam (stage B)
```

```bash
cd infra/terraform/network
terraform init
terraform apply -var-file=../dev.tfvars

cd ../iam
terraform init
# Stage A only — see below
terraform apply \
  -target=aws_iam_role.eks_cluster \
  -target=aws_iam_role_policy_attachment.eks_cluster \
  -target=aws_iam_role.eks_node \
  -target=aws_iam_role_policy_attachment.eks_node_worker \
  -target=aws_iam_role_policy_attachment.eks_node_ecr \
  -target=aws_iam_role_policy_attachment.eks_node_cni \
  -target=aws_iam_role.ebs_csi \
  -target=aws_iam_role_policy_attachment.ebs_csi \
  -target=aws_iam_role.cert_manager \
  -target=aws_iam_policy.cert_manager_route53 \
  -target=aws_iam_role_policy_attachment.cert_manager_route53

cd ../eks
terraform init
terraform apply -var='api_public_access_cidrs=["YOUR.IP.ADDR.0/24"]'
```

`api_public_access_cidrs` has no default and its validation rejects both an empty list and `0.0.0.0/0`, so the cluster API cannot be opened to the internet by configuration.

Expect 15 to 20 minutes for the `eks` root.

### The iam root is applied in two stages

It holds two unrelated groups:

| Group | Depends on |
|---|---|
| IAM roles and policies | nothing |
| `aws_route53_record.wtt_demo` in `dns-demo.tf` | **a load balancer that Kubernetes creates in step 7** |

The record's `alias.name` is the load balancer hostname, written in as a literal. On a clean build it does not exist yet, while the `eks` root needs the IAM roles immediately.

**Stage A**, above, applies the eleven IAM resources by address. `-target` is the supported mechanism for a partial apply. Terraform warns that the apply was targeted; that is expected here, not an error. **Do not run an apply that is expected to fail.**

Confirm the three outputs the `eks` root reads:

```bash
cd infra/terraform/iam
terraform output eks_cluster_role_arn
terraform output eks_node_role_arn
terraform output ebs_csi_role_arn
```

All three must return an ARN. **Stage B** is step 11.

### A dependency that needs no handling

`eks/cert-manager-identity.tf` creates a Pod Identity association naming a service account that does not exist until step 5. That is safe: an association may precede its service account and begins working when the service account appears.

## 4. Cluster access

```bash
aws eks update-kubeconfig --region eu-north-1 --name wtt-demo-eks
kubectl get nodes -o wide            # 2 Ready, no public addresses
kubectl get storageclass             # gp3
```

Generated on demand. Never commit a kubeconfig.

## 5. Gateway API CRDs and cert-manager — MANUAL

CRDs must exist before Traefik, which will not start its Gateway provider without them.

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml
kubectl get crd | grep gateway.networking.k8s.io

kubectl get crd gateways.gateway.networking.k8s.io \
  -o jsonpath='{.metadata.annotations.gateway\.networking\.k8s\.io/bundle-version}{"\n"}'   # v1.6.1
```

Standard channel is sufficient; nothing here needs the experimental channel.

cert-manager comes from an OCI registry, so there is no `helm repo add`:

```bash
helm install cert-manager oci://quay.io/jetstack/charts/cert-manager \
  --namespace cert-manager --create-namespace \
  --version v1.21.2 \
  --set crds.enabled=true

kubectl -n cert-manager get pods     # controller, webhook, cainjector Running
helm list -n cert-manager            # chart cert-manager-v1.21.2
```

The service account must be named `cert-manager` in namespace `cert-manager` to match the Pod Identity association from step 3. That is the chart default. Confirm credentials reach the pod:

```bash
kubectl -n cert-manager exec deploy/cert-manager -- env | grep -i AWS_CONTAINER
```

## 6. Base Kubernetes resources

```bash
kubectl apply -f k8s/base/namespaces.yaml
kubectl apply -f k8s/base/storage/gp3.yaml
```

`vote-prod` is created and intentionally left empty.

> `gp3.yaml` sets `reclaimPolicy: Delete`. Deleting a claim later destroys the volume and all data. [Block 06](../roadmap.md#next-block) addresses this; consider applying 06-A immediately after step 8.

## 7. Traefik — MANUAL

```bash
helm repo add traefik https://traefik.github.io/charts
helm repo update

# Replace the two subnet IDs in values-public.yaml first
aws ec2 describe-subnets --region eu-north-1 \
  --filters "Name=tag:Name,Values=wtt-demo-public-*" \
  --query 'Subnets[].{Id:SubnetId,AZ:AvailabilityZone}' --output table

helm install traefik traefik/traefik \
  --namespace traefik --create-namespace \
  --version 41.7.1 \
  -f k8s/platform/traefik/values.yaml \
  -f k8s/platform/traefik/values-public.yaml

helm list -n traefik                 # chart traefik-41.7.1
```

`values.yaml` enables only the Gateway API provider and creates a `GatewayClass` plus a `Gateway` with listeners `web:8000` and `websecure:8443`. `values-public.yaml` switches the Service to `LoadBalancer` with Network Load Balancer annotations.

The `websecure` listener references Secret `wtt-demo-tls`, which does not exist until step 10, so the Gateway will not be fully `Programmed` yet. Expected.

```bash
kubectl -n traefik get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].hostname}{"\n"}'
```

**Record that hostname.** It is the alias target for step 11.

## 8. PostgreSQL credentials and data services — MANUAL

The Secret is deliberately not in Git, and must exist before the StatefulSet, which consumes it with `envFrom`.

```bash
kubectl -n vote-dev create secret generic postgres-credentials \
  --from-literal=POSTGRES_USER='<user>' \
  --from-literal=POSTGRES_PASSWORD="$(python3 scripts/pass.py --length 32)" \
  --from-literal=POSTGRES_DB='<database>'

# Verify key names without printing values
kubectl -n vote-dev get secret postgres-credentials \
  -o jsonpath='{range $k,$v := .data}{$k}{"\n"}{end}'
```

All three keys are required. Never echo the password, never pass it on a shared command line, never commit it. Rotation: `scripts/rotate_k8s_postgres_password.py`.

```bash
kubectl apply -f k8s/base/postgres/
kubectl apply -f k8s/base/redis/
kubectl -n vote-dev get pods -w
```

Because `volumeBindingMode: WaitForFirstConsumer`, the volume is created in the zone where the pod is scheduled, and from then on the pod can run only in that zone.

## 9. Application and routes

Images are public in GHCR, so no pull secret is needed.

```bash
kubectl apply -f k8s/apps/dev/applications.yaml
kubectl apply -f k8s/apps/dev/httproutes.yaml
kubectl apply -f k8s/apps/dev/result-redirect.yaml
kubectl apply -f k8s/apps/dev/http-to-https.yaml
kubectl -n vote-dev get pods
```

Confirm the images are reachable first:

```bash
for s in vote result worker; do
  tag=$(grep -oE "wtt-demo/$s:[^ ]+" k8s/apps/dev/applications.yaml | head -1)
  echo "== $tag"; docker manifest inspect "ghcr.io/asyachin/$tag" >/dev/null && echo ok
done
```

To rebuild an image by hand, if CI is unavailable:

```bash
cd app/vote
docker build -t ghcr.io/asyachin/wtt-demo/vote:manual-$(git rev-parse --short=7 HEAD) .
docker push ghcr.io/asyachin/wtt-demo/vote:manual-$(git rev-parse --short=7 HEAD)
```

Normally CI builds, scans and publishes on every push to `dev`; see [../architecture.md](../architecture.md#delivery-pipeline).

### Route order matters within the application

The two rules inside the `result` route are order-sensitive: `/result/socket.io` must be matched before `/result`, and only `/result` carries the `URLRewrite`. The redirect route attaches only to the `web` listener; the application routes attach only to `websecure`.

## 10. TLS

Staging first. Let's Encrypt production permits five duplicate certificates per week, and a misconfigured solver exhausts that in an afternoon.

```bash
kubectl apply -f k8s/platform/cert-manager/clusterissuer-staging.yaml
kubectl apply -f k8s/platform/cert-manager/certificate-staging.yaml
kubectl -n traefik get certificate -w          # wtt-demo-staging Ready=True
```

If it stalls, the solver is the usual cause:

```bash
kubectl -n traefik get certificaterequest,order,challenge
kubectl -n traefik describe challenge | tail -40
```

Only once staging works:

```bash
kubectl apply -f k8s/platform/cert-manager/clusterissuer-production.yaml
kubectl apply -f k8s/platform/cert-manager/certificate-production.yaml
kubectl -n traefik get certificate wtt-demo -w  # Ready=True, Secret wtt-demo-tls created
```

Certificates cover one name. There is no wildcard.

## 11. Route 53 record — stage B of the iam root

```bash
NLB=$(kubectl -n traefik get svc traefik \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
echo "$NLB"                       # must be non-empty
```

Set `alias.name` in `infra/terraform/iam/dns-demo.tf` to that value, then run a full untargeted apply:

```bash
cd infra/terraform/iam
terraform plan                    # expect exactly 1 to add, 0 to change, 0 to destroy
terraform apply

dig +short wtt-demo.syachin.de    # two addresses, one per zone
```

If the plan proposes anything else, stage A was incomplete.

The alias also needs the load balancer's canonical hosted zone ID, which is region-specific. `Z1UDT6IFJ4EJM` is the value for Network Load Balancers in `eu-north-1`. For another region:

```bash
aws elbv2 describe-load-balancers --region "$AWS_REGION" \
  --query "LoadBalancers[?DNSName=='$NLB'].CanonicalHostedZoneId" --output text
```

### The remaining manual dependency

Stage B cannot be automated as the code stands, because the hostname is a literal that Terraform neither computes nor consults a data source for. Consequences:

- A clean rebuild needs a human to copy one value from `kubectl` into a `.tf` file between step 7 and step 11.
- If the Traefik Service is ever recreated, the record silently points at a load balancer that no longer exists, and `terraform plan` stays empty. Detection in [operate.md](operate.md).

Two permanent fixes, both deferred because they change Terraform or Kubernetes:

| Fix | Effect |
|---|---|
| Deploy `external-dns` and let it maintain the record from the `Gateway` | Moves DNS ownership to Kubernetes, where the load balancer already lives. Removes the manual step and the silent-breakage class. |
| Keep Terraform ownership, replace the literal with a `data "aws_lb"` lookup, gate the record behind a `count` variable | Still two stages, but stage B becomes a variable rather than a file edit |

The first is better and would also move the record out of the `iam` root. See [../decisions/0017-terraform-multi-root.md](../decisions/0017-terraform-multi-root.md).

## 12. Argo CD — MANUAL

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm install argocd argo/argo-cd \
  --namespace argocd --create-namespace \
  -f k8s/platform/argocd/values.yaml

kubectl -n argocd get pods
```

The values set `server.service.type: ClusterIP` and `server.insecure: true`. There is **no public route**: access is by port-forward only.

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:80
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

Do not record that password anywhere in the repository.

Then register the applications:

```bash
kubectl apply -f k8s/platform/argocd/demo-application.yaml     # isolated proving workload
kubectl apply -f k8s/platform/argocd/vote-dev-application.yaml # the application itself
kubectl -n argocd get applications
```

Both Applications have `automated` sync with `selfHeal: true` and **`prune: false`**. On a rebuild the resources already exist from step 9, so Argo CD adopts them rather than creating them. Confirm adoption did not replace anything:

```bash
kubectl -n vote-dev get deploy,svc -o custom-columns='KIND:.kind,NAME:.metadata.name,UID:.metadata.uid'
```

Compare the UIDs before and after. A changed UID means a resource was recreated.

## 13. Verify

Run [operate.md](operate.md) section 1, then open both pages in a browser with the console visible, vote, and watch the count change. A status code does not prove the page works — that lesson came from the `/result` and mixed-content defects.

## Adapting to another organisation

| Change | Where |
|---|---|
| Account, region, project name | `infra/terraform/dev.tfvars`, variable defaults, `allowed_account_ids` in all four `versions.tf`, backend blocks |
| State bucket | `bootstrap/bootstrap.tfvars` and the backend block of all four roots. Globally unique. |
| Hostname | Terraform, Traefik values, both issuers, both certificates, all four `HTTPRoute` objects |
| Hosted zone | `iam/cert-manager.tf`, `iam/dns-demo.tf`, both issuers |
| ACME email | both `ClusterIssuer` manifests |
| Subnet IDs | `k8s/platform/traefik/values-public.yaml` |
| Image registry | `k8s/apps/dev/applications.yaml`, and the workflow in `.github/workflows/ci-images.yml` |
| Git repository | `k8s/platform/argocd/*.yaml` |
| Node size or capacity type | `eks/variables.tf`. Mind the VPC CNI pod-density limit. |

## Known reproducibility gaps

| Gap | Effect | Owner |
|---|---|---|
| Four chart and CRD versions pinned in prose, not in code | A rebuild is version-identical only if the operator follows this document | Future work |
| Route 53 alias depends on a Kubernetes-generated hostname | A human step between step 7 and step 11 | Deferred |
| Subnet IDs hardcoded in Traefik values | Must be edited for a new account | Deferred |
| The Secret is manual | A rebuild stops until an operator creates it | [ADR 0020](../decisions/0020-manual-postgres-secret.md) |
| Argo CD manages only Deployments and Services | Everything else needs `kubectl apply` | Deferred |
| **This procedure has never been executed end to end** | Unknown unknowns | Block 10 |
