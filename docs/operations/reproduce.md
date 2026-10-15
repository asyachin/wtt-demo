# Rebuild from a clean environment

How to build this platform in a fresh AWS account. Every command matches the repository at `a4d979f`.

> **This is a documented procedure, not a verified one.** It was written by reading the Terraform roots, the manifests and the Git history. **A clean-environment reproduction has never been performed.** Block 10 exists to run it and correct whatever is wrong. Expect to find gaps, particularly in the steps marked **MANUAL**.

## Steps that are not automated

Read this before starting. The platform is not reproducible from `terraform apply` alone.

| Step | Why it is manual |
|---|---|
| Gateway API CRD installation | Applied with `kubectl`. **The version was not recorded.** |
| Traefik installation | Helm release. Chart `41.7.1` per a comment in the values file. The install command was not recorded. |
| cert-manager installation | Helm release. **Chart version was not recorded.** |
| `postgres-credentials` Secret | Created by the operator. Deliberately never in Git. |
| Traefik subnet IDs | Hardcoded in `k8s/platform/traefik/values-public.yaml`. New account means new IDs. |
| Route 53 alias target | The NLB hostname is hardcoded in `infra/terraform/iam/dns-demo.tf`. Kubernetes generates it, so it cannot be known before Traefik is installed. |
| Route 53 hosted zone | Pre-existing. Not created by this project. |
| Operator IP allowlist | `api_public_access_cidrs` has no default and must be supplied. |

Recording the three chart and CRD versions is scope item 05-B in [../blocks/05-gitops.md](../blocks/05-gitops.md). Until that is done, a rebuild requires choosing versions, and the result will not be identical to the current deployment.

## Operator input required

No default exists for these. Substitute your own values throughout.

| Value | Current | Where |
|---|---|---|
| AWS account ID | `899088266068` | `infra/terraform/dev.tfvars`, defaults in `iam/variables.tf` and `eks/variables.tf`, `allowed_account_ids` in every `versions.tf` |
| State bucket name | `wtt-demo-tfstate-899088266068-eu-north-1` | `bootstrap/bootstrap.tfvars` and the `backend` block of all four roots |
| Region | `eu-north-1` | throughout |
| Route 53 hosted zone ID | `Z030020038RZDL2JLFT70` | `iam/cert-manager.tf`, `iam/dns-demo.tf`, both `ClusterIssuer` manifests |
| Public hostname | `wtt-demo.syachin.de` | `iam/cert-manager.tf`, `iam/dns-demo.tf`, Traefik values, both issuers, both certificates, all `HTTPRoute` objects |
| ACME contact email | `asyachin@gmail.com` | both `ClusterIssuer` manifests |
| Operator IP CIDRs | none | `api_public_access_cidrs` |
| Public subnet IDs | `subnet-0b7a30aac89e73957`, `subnet-063c2d2902dfe90df` | `k8s/platform/traefik/values-public.yaml` |
| NLB hostname | `ab6ca8d8903fc411db48922a559fdd15-f9a53d15b6b1bfdf.elb.eu-north-1.amazonaws.com` | `iam/dns-demo.tf` |
| PostgreSQL credentials | not in Git | the `postgres-credentials` Secret |
| GHCR image tags | `vote:9a9bb9e`, `result:f0ea1a0`, `worker:f75d7b7` | `k8s/apps/dev/applications.yaml` |

The backend `bucket` cannot be supplied by a variable: Terraform requires backend configuration to be literal. Either edit the four `versions.tf` and `backend.tf` files, or pass `-backend-config`.

## Prerequisites

| Tool | Required | Verified present on the build host |
|---|---|---|
| `terraform` | `>= 1.16.0, < 1.17.0`, enforced by every root | 1.16 |
| `aws` CLI | v2, with credentials able to create VPC, IAM, EKS, S3 | present |
| `kubectl` | 1.33 or later for a 1.36 cluster | 1.35 |
| `helm` | 3.x | 3.20 |
| `git` | any recent | present |
| `python3` | 3.11+, for the test suite and scripts | 3.12 |
| `docker` | only to build images | 29.8 |
| `openssl`, `dig`, `curl` | for verification | present |

The AWS provider is pinned to exactly `6.68.0`. Lock files are committed, so run `terraform init` without `-upgrade` to reproduce the same provider.

## 1. AWS account preparation

```bash
aws sts get-caller-identity          # confirm the account ID matches the configuration
aws configure get region             # or export AWS_REGION=eu-north-1
```

A Route 53 public hosted zone must already exist for the parent domain, with its name servers delegated. This project creates a record inside an existing zone; it does not create or delegate the zone.

```bash
aws route53 list-hosted-zones --query 'HostedZones[].{Id:Id,Name:Name}' --output table
```

## 2. Terraform state backend

Run once. Uses local state, because the bucket it creates is the backend for everything else.

```bash
cd infra/terraform/bootstrap
terraform init
terraform apply -var-file=bootstrap.tfvars
```

Creates a versioned, AES256-encrypted, private S3 bucket with `BucketOwnerEnforced` ownership and `prevent_destroy` set. Locking is native S3 `use_lockfile = true`; **there is no DynamoDB table.**

The `bootstrap` root keeps local state. That state file is not committed and is not critical: the bucket can be re-imported if lost.

## 3. Terraform roots, in order

The order is mandatory. `eks` reads both `network` and `iam` through `terraform_remote_state`.

```
bootstrap  →  network  →  iam  →  eks
```

```bash
cd infra/terraform/network
terraform init
terraform apply -var-file=../dev.tfvars

cd ../iam
terraform init
terraform apply                      # variables have defaults

cd ../eks
terraform init
terraform apply -var='api_public_access_cidrs=["YOUR.IP.ADDR.0/24"]'
```

`api_public_access_cidrs` has no default and its validation rejects both an empty list and `0.0.0.0/0`, so the cluster API cannot be opened to the internet by configuration.

Expect roughly 15 to 20 minutes for the `eks` root: the control plane and the node group dominate.

What each root creates:

| Root | Creates |
|---|---|
| `network` | VPC `10.42.0.0/16`, two public and two private subnets across two zones, IGW, one NAT Gateway with an EIP, route tables, and the `kubernetes.io/role/elb` and `kubernetes.io/role/internal-elb` subnet tags |
| `iam` | EKS cluster role, node role with worker, ECR-pull and CNI policies, EBS CSI role, cert-manager role with the least-privilege Route 53 policy, **and the Route 53 A record** |
| `eks` | Cluster 1.36, `vpc-cni`, `kube-proxy`, `coredns`, `eks-pod-identity-agent`, `aws-ebs-csi-driver` with a Pod Identity association, the managed node group, and the cert-manager Pod Identity association |

### A circular dependency to expect

`iam/dns-demo.tf` creates a Route 53 alias pointing at an NLB hostname that does not exist yet, because Kubernetes creates the NLB in step 7. On a clean build, either comment that resource out for the first apply and re-apply after step 7, or accept that the first apply fails on it.

This is the Terraform-versus-Kubernetes ownership problem described in [../lessons.md](../lessons.md). Resolving it properly means `external-dns` or an accepted manual step, and it is deferred.

Similarly, `eks/cert-manager-identity.tf` names the service account `cert-manager` in namespace `cert-manager`, which does not exist until step 6. A Pod Identity association can be created before its service account exists and simply starts working when it appears, so no revisit is needed there.

## 4. Cluster access

```bash
aws eks update-kubeconfig --region eu-north-1 --name wtt-demo-eks
kubectl get nodes -o wide            # expect 2 Ready, no public addresses
kubectl get storageclass             # expect gp3
```

Generated on demand. Never commit a kubeconfig.

## 5. Gateway API CRDs — MANUAL

Must be installed before Traefik, which will not start its Gateway provider without them.

```bash
# Substitute the version you intend to standardise on.
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/<VERSION>/standard-install.yaml

kubectl get crd | grep gateway.networking.k8s.io
```

**The version used in the current deployment was not recorded.** Read it from the running cluster:

```bash
kubectl get crd gateways.gateway.networking.k8s.io \
  -o jsonpath='{.metadata.annotations.gateway\.networking\.k8s\.io/bundle-version}{"\n"}'
```

Standard channel is sufficient. `HTTPRoute`, `Gateway` and `GatewayClass` are all in it; nothing here needs the experimental channel.

## 6. cert-manager — MANUAL

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --version <VERSION> \
  --set crds.enabled=true

kubectl -n cert-manager get pods     # controller, webhook, cainjector all Running
```

**Chart version not recorded.** Read it from the cluster with `helm list -A`.

The service account must be named `cert-manager` in namespace `cert-manager` to match the Pod Identity association created in step 3. That is the chart default.

Pod Identity requires the `eks-pod-identity-agent` add-on, which step 3 installed. Confirm credentials are reaching the pod before relying on it:

```bash
kubectl -n cert-manager exec deploy/cert-manager -- env | grep -i AWS_CONTAINER
```

## 7. Traefik — MANUAL

```bash
helm repo add traefik https://traefik.github.io/charts
helm repo update

# Edit k8s/platform/traefik/values-public.yaml first:
# replace the two subnet IDs with your public subnet IDs.
kubectl get subnets 2>/dev/null || \
  aws ec2 describe-subnets --region eu-north-1 \
    --filters "Name=tag:Name,Values=wtt-demo-public-*" \
    --query 'Subnets[].{Id:SubnetId,AZ:AvailabilityZone}' --output table

helm install traefik traefik/traefik \
  --namespace traefik --create-namespace \
  --version 41.7.1 \
  -f k8s/platform/traefik/values.yaml \
  -f k8s/platform/traefik/values-public.yaml
```

Chart `41.7.1`, per the comment at the top of `values.yaml`. The install command itself was not recorded, so the command above is reconstructed from the values files that exist.

`values.yaml` enables only the Gateway API provider, disables the Ingress and CRD providers, and creates a `GatewayClass` named `traefik` plus a `Gateway` named `traefik-gateway` with listeners `web:8000` HTTP and `websecure:8443` HTTPS. `values-public.yaml` switches the Service to `LoadBalancer` with NLB annotations.

The `websecure` listener references Secret `wtt-demo-tls`, which does not exist until step 9, so the Gateway will not be fully `Programmed` yet. That is expected.

```bash
kubectl -n traefik get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].hostname}{"\n"}'
```

**Record that hostname.** It is the alias target for step 10 and the value currently hardcoded in `iam/dns-demo.tf`.

## 8. Base Kubernetes resources

```bash
kubectl apply -f k8s/base/namespaces.yaml
kubectl apply -f k8s/base/storage/gp3.yaml
```

Creates namespaces `vote-dev` and `vote-prod`, and the `gp3` StorageClass.

`vote-prod` is created and intentionally left empty. It is not a production environment; see [../architecture.md](../architecture.md#environment-model).

> `k8s/base/storage/gp3.yaml` sets `reclaimPolicy: Delete`. Deleting the PVC later destroys the volume and all data. [Block 06](../blocks/06-data-durability.md) addresses this.

## 9. PostgreSQL credentials — MANUAL

The Secret is deliberately not in Git. Create it before the data services, because the StatefulSet consumes it with `envFrom`.

```bash
kubectl -n vote-dev create secret generic postgres-credentials \
  --from-literal=POSTGRES_USER='<user>' \
  --from-literal=POSTGRES_PASSWORD="$(python3 scripts/pass.py --length 32)" \
  --from-literal=POSTGRES_DB='<database>'
```

All three keys are required. `postgres` reads all of them via `envFrom`; `result` and `worker` reference them individually with `secretKeyRef`.

Verify the key names without printing any value:

```bash
kubectl -n vote-dev get secret postgres-credentials \
  -o jsonpath='{range $k,$v := .data}{$k}{"\n"}{end}'
```

Never echo the password, never pass it on a shared shell command line, and never commit it. Rotation: `scripts/rotate_k8s_postgres_password.py`.

## 10. Data services

```bash
kubectl apply -f k8s/base/postgres/
kubectl apply -f k8s/base/redis/
kubectl -n vote-dev get pods -w
```

PostgreSQL binds a 5 GiB `gp3` PVC. Because `volumeBindingMode: WaitForFirstConsumer`, the volume is created in whichever availability zone the pod is scheduled into — and from then on the pod can only run in that zone.

## 11. TLS

Staging first. Let's Encrypt production permits five duplicate certificates per week, and a misconfigured solver exhausts that in an afternoon.

```bash
kubectl apply -f k8s/platform/cert-manager/clusterissuer-staging.yaml
kubectl apply -f k8s/platform/cert-manager/certificate-staging.yaml
kubectl -n traefik get certificate -w            # wtt-demo-staging → Ready=True
```

If it does not become ready, the solver is the usual cause:

```bash
kubectl -n traefik get certificaterequest,order,challenge
kubectl -n traefik describe challenge | tail -40
```

Only once staging works:

```bash
kubectl apply -f k8s/platform/cert-manager/clusterissuer-production.yaml
kubectl apply -f k8s/platform/cert-manager/certificate-production.yaml
kubectl -n traefik get certificate wtt-demo -w   # Ready=True, Secret wtt-demo-tls created
```

Both issuers use a DNS-01 Route 53 solver with a `dnsNames` selector, authenticating through the Pod Identity association from step 3. The IAM policy permits only `TXT` changes to exactly `_acme-challenge.<hostname>` in one zone.

Certificates cover one name. There is no wildcard.

## 12. Route 53 record

Now that the NLB hostname from step 7 is known, update `infra/terraform/iam/dns-demo.tf` with it and apply:

```bash
cd infra/terraform/iam
terraform apply
```

```bash
dig +short wtt-demo.syachin.de                   # two addresses, one per zone
```

The alias also needs the NLB's canonical hosted zone ID, which is region-specific. `Z1UDT6IFJ4EJM` is the value for NLBs in `eu-north-1`.

## 13. Application

```bash
kubectl apply -f k8s/apps/dev/applications.yaml
kubectl apply -f k8s/apps/dev/httproutes.yaml
kubectl apply -f k8s/apps/dev/result-redirect.yaml
kubectl -n vote-dev get pods
```

Images are public in GHCR, so no pull secret is needed:

| Image | Tag |
|---|---|
| `ghcr.io/asyachin/wtt-demo/vote` | `9a9bb9e` |
| `ghcr.io/asyachin/wtt-demo/result` | `f0ea1a0` |
| `ghcr.io/asyachin/wtt-demo/worker` | `f75d7b7` |

Confirm they are reachable before applying:

```bash
for i in vote:9a9bb9e result:f0ea1a0 worker:f75d7b7; do
  echo "== $i"; docker manifest inspect "ghcr.io/asyachin/wtt-demo/$i" >/dev/null && echo ok
done
```

There is no CI, so images are built by hand. To rebuild one:

```bash
cd app/vote
docker build -t ghcr.io/asyachin/wtt-demo/vote:$(git rev-parse --short=7 HEAD) .
docker push ghcr.io/asyachin/wtt-demo/vote:$(git rev-parse --short=7 HEAD)
```

Then update the tag in `k8s/apps/dev/applications.yaml` and apply. The tag convention is the short SHA of the commit whose source produced the image, which is what makes a running image traceable to a commit.

### Apply order within the application

`httproutes.yaml` and `result-redirect.yaml` can be applied in any order, but the two rules inside the `result` route are order-sensitive as written: `/result/socket.io` must be matched before `/result`, and only `/result` carries the `URLRewrite`. See [../lessons.md](../lessons.md).

## 14. Verify

Run the whole of [verify.md](verify.md). The minimum:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://wtt-demo.syachin.de/
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' https://wtt-demo.syachin.de/result
curl -sS -o /dev/null -w '%{http_code}\n' https://wtt-demo.syachin.de/result/
```

Then open both pages in a browser with the console visible, vote, and watch the count change. A status code does not prove the page works; that is the lesson from the `/result` and mixed-content defects.

## Adapting to another organisation

| Change | Where |
|---|---|
| Account, region, project name | `infra/terraform/dev.tfvars`, variable defaults, `allowed_account_ids` in all four `versions.tf`, backend blocks |
| State bucket | `bootstrap/bootstrap.tfvars` and the backend block of all four roots. Must be globally unique. |
| Hostname | `iam/cert-manager.tf`, `iam/dns-demo.tf`, `k8s/platform/traefik/values.yaml`, both issuers, both certificates, all three `HTTPRoute` objects |
| Hosted zone | `iam/cert-manager.tf`, `iam/dns-demo.tf`, both issuers |
| ACME email | both `ClusterIssuer` manifests |
| Subnet IDs | `k8s/platform/traefik/values-public.yaml` |
| Image registry | `k8s/apps/dev/applications.yaml` |
| Node size or capacity type | `eks/variables.tf`. Mind the VPC CNI pod-density limit; see [../lessons.md](../lessons.md). |

The hostname appears in roughly ten places across Terraform and manifests. It is not parameterised. Grep for it rather than trusting this list:

```bash
grep -rn 'wtt-demo\.syachin\.de' infra/ k8s/
```

## Known reproducibility gaps

| Gap | Effect | Owner |
|---|---|---|
| Three chart and CRD versions unrecorded | A rebuild will not be version-identical | Block 05, item 05-B |
| Route 53 alias depends on a Kubernetes-generated hostname | The first apply of the `iam` root cannot succeed on a clean build | Deferred |
| Subnet IDs hardcoded in Traefik values | Must be edited for a new account | Deferred |
| The Secret is manual | A rebuild stops until an operator creates it | [ADR 0020](../decisions/0020-manual-postgres-secret.md) |
| No CI | Images are built and pushed by hand | Block 07 |
| **This procedure has never been executed end to end** | Unknown unknowns | Block 10 |
