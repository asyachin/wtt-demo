# Teardown and cost control

Destroying this platform correctly requires an order that is not obvious. `terraform destroy` alone leaves resources running and billing.

## Why order matters

Two resources are not owned by Terraform:

| Resource | Owner | Consequence |
|---|---|---|
| The Network Load Balancer | The Traefik `Service` of type `LoadBalancer`. Kubernetes asked AWS for it. | `terraform destroy` does not remove it. Orphaned, it bills hourly indefinitely. |
| The PostgreSQL EBS volume | Provisioned dynamically by the EBS CSI driver through the PVC | Its fate is decided by the reclaim policy, not by Terraform |

A further complication: destroying the EKS cluster while a `Service` of type `LoadBalancer` still exists removes the controller that would have cleaned up the NLB. The load balancer then survives with nothing managing it, and it must be deleted by hand in the console or the CLI.

**Kubernetes-owned resources are deleted first. Terraform second.**

## Cost context

Roughly 0.35 USD per hour, about 250 to 290 USD per month at list price. Idle cost is nearly the whole cost: a cluster serving no traffic bills almost the same as a busy one.

| Item | Approximate monthly |
|---|---|
| EKS control plane | ~73 USD |
| 2 × `t3.large` On-Demand | ~133 USD |
| NAT Gateway, hourly plus data processing | ~33 USD |
| Network Load Balancer | ~17 USD |
| EBS volumes, 85 GiB total | ~8 USD |
| Route 53 zone, S3 state, data transfer | ~3 USD |

Estimates, not billing data. See [../architecture.md](../architecture.md#cost-estimate).

## Decide first: keep or destroy

| Option | Hourly cost | Public URL | Recovery |
|---|---|---|---|
| Leave everything running | full | works | none needed |
| Scale the node group to zero | control plane, NAT, NLB only | **breaks** | minutes |
| Full teardown, keep state bucket and zone | near zero | **breaks** | 20 to 30 minutes, and the DNS record must be updated with the new NLB hostname |
| Full teardown including the bucket and zone | zero | breaks | a full rebuild |

Scaling nodes to zero saves only the node cost, roughly half. The control plane, NAT Gateway and NLB keep billing. It is rarely the right choice: either the demonstration is needed and it runs, or it is not and it is destroyed.

Run the full teardown when the interview process ends.

## Before starting

```bash
export AWS_REGION=eu-north-1
aws eks update-kubeconfig --region eu-north-1 --name wtt-demo-eks
aws sts get-caller-identity          # confirm the account

# Record what exists, so you can confirm it is gone afterwards
kubectl -n traefik get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].hostname}{"\n"}'
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerArn' --output text
aws ec2 describe-volumes --query 'Volumes[].VolumeId' --output text
aws ec2 describe-nat-gateways --filter Name=state,Values=available \
  --query 'NatGateways[].NatGatewayId' --output text
```

### Back up the data, if it matters

```bash
kubectl -n vote-dev exec postgres-0 -- \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > /tmp/votes-$(date -u +%Y%m%dT%H%M%SZ).dump
ls -l /tmp/votes-*.dump
```

There is no backup system, so this manual dump is the only copy. Step 3 destroys the database. For a demonstration the votes are probably disposable, but that should be a decision rather than a discovery.

## Step 1 — Delete the Traefik Service

This is what releases the NLB, and it must happen while the cluster and its controllers are still alive.

```bash
helm uninstall traefik -n traefik

# Or, if only the load balancer should go:
# kubectl -n traefik delete svc traefik

# The NLB deletion is asynchronous. Wait for it.
for i in $(seq 1 30); do
  n=$(aws elbv2 describe-load-balancers --query 'length(LoadBalancers)' --output text)
  echo "load balancers remaining: $n"; [ "$n" = "0" ] && break; sleep 10
done
```

Confirm before continuing:

```bash
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName'
```

This must return an empty list. If it does not, delete the load balancer explicitly before destroying the cluster, or it becomes an orphan.

Uninstalling Traefik also removes the `GatewayClass` and `Gateway` it created, so the public demonstration is down from this point.

## Step 2 — Remove the DNS record

```bash
cd infra/terraform/iam
terraform destroy -target=aws_route53_record.wtt_demo
```

Removing the record before the NLB is gone prevents a window where DNS points at a load balancer that no longer exists. Order here is a courtesy rather than a cost matter.

The hosted zone itself is not managed by this project and is not destroyed.

## Step 3 — Delete the persistent volumes

Decide deliberately, because the outcome differs by reclaim policy.

```bash
PV=$(kubectl -n vote-dev get pvc data-postgres-0 -o jsonpath='{.spec.volumeName}')
kubectl get pv "$PV" -o jsonpath='{.spec.persistentVolumeReclaimPolicy}{"\n"}'
```

| Policy | Deleting the PVC |
|---|---|
| `Delete` — the current setting | The EBS volume is destroyed. **All voting data is lost, irreversibly.** |
| `Retain` — after [Block 06](../blocks/06-data-durability.md) | The volume survives and **keeps billing** until deleted explicitly |

```bash
kubectl -n vote-dev delete statefulset postgres
kubectl -n vote-dev delete pvc --all

# With Retain, the volume must then be removed by hand
kubectl get pv
aws ec2 describe-volumes --filters Name=status,Values=available \
  --query 'Volumes[].{Id:VolumeId,Size:Size,Created:CreateTime}'
# aws ec2 delete-volume --volume-id vol-...
```

An available, unattached EBS volume is the resource most often forgotten. It is cheap, which is exactly why nobody notices it for months.

## Step 4 — Optional: remove remaining Kubernetes resources

Not strictly necessary, since destroying the cluster removes everything in it. Worth doing if the cluster might be kept.

```bash
kubectl delete -f k8s/apps/dev/ --ignore-not-found
kubectl delete -f k8s/platform/cert-manager/ --ignore-not-found
helm uninstall cert-manager -n cert-manager
kubectl delete -f k8s/base/namespaces.yaml --ignore-not-found
```

Deleting the `Certificate` objects does not revoke the issued certificates; they simply expire. The cert-manager ACME account key is deleted with its namespace, which is harmless.

## Step 5 — Destroy the Terraform roots, in reverse order

The `eks` root reads `network` and `iam` through `terraform_remote_state`, so destroying out of order leaves dangling references.

```
eks  →  iam  →  network      (bootstrap is kept)
```

```bash
cd infra/terraform/eks
terraform destroy -var='api_public_access_cidrs=["YOUR.IP.ADDR.0/24"]'

cd ../iam
terraform destroy

cd ../network
terraform destroy -var-file=../dev.tfvars
```

Allow 10 to 15 minutes for the `eks` root. The node group drains before the control plane is removed.

If the `network` destroy fails on a dependency violation, something is still attached inside the VPC — usually an orphaned NLB from step 1, or an ENI left behind by the CNI:

```bash
aws ec2 describe-network-interfaces \
  --filters Name=vpc-id,Values=<vpc-id> \
  --query 'NetworkInterfaces[].{Id:NetworkInterfaceId,Desc:Description,Status:Status}'
```

Delete the attachment, then retry the destroy. Never force-delete the state to make an error disappear.

## Step 6 — Decide about the state bucket

The `bootstrap` root is deliberately kept. It holds Terraform state for everything else, has `prevent_destroy` set, and costs cents per month.

Destroy it only if the project is being abandoned entirely, and only after emptying it:

```bash
# Irreversible. The state history goes with it.
# Remove the prevent_destroy lifecycle block first, then:
# aws s3 rm s3://wtt-demo-tfstate-899088266068-eu-north-1 --recursive
# cd infra/terraform/bootstrap && terraform destroy -var-file=bootstrap.tfvars
```

Also consider keeping the Route 53 hosted zone, at 0.50 USD per month, since re-delegating a domain takes longer than rebuilding the platform.

## Step 7 — Verify zero cost

Every one of these must return an empty list.

```bash
aws eks list-clusters --region eu-north-1

aws ec2 describe-instances --region eu-north-1 \
  --filters Name=instance-state-name,Values=running,pending \
  --query 'Reservations[].Instances[].InstanceId'

aws ec2 describe-nat-gateways --region eu-north-1 \
  --filter Name=state,Values=available,pending \
  --query 'NatGateways[].NatGatewayId'

aws ec2 describe-addresses --region eu-north-1 \
  --query 'Addresses[].{Ip:PublicIp,Assoc:AssociationId}'

aws elbv2 describe-load-balancers --region eu-north-1 \
  --query 'LoadBalancers[].LoadBalancerArn'

aws ec2 describe-volumes --region eu-north-1 \
  --query 'Volumes[].VolumeId'

aws ec2 describe-vpcs --region eu-north-1 \
  --filters Name=tag:Project,Values=wtt-demo \
  --query 'Vpcs[].VpcId'
```

An unassociated Elastic IP bills even though it does nothing, which is why `describe-addresses` is in the list.

Confirm against billing 24 hours later, since the console lags:

```bash
aws ce get-cost-and-usage --region us-east-1 \
  --time-period Start=$(date -u -d yesterday +%F),End=$(date -u +%F) \
  --granularity DAILY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE
```

## The three resources most often left behind

| Resource | Why it is missed | How to find it |
|---|---|---|
| The NLB | Created by Kubernetes, not Terraform. `terraform destroy` reports success without touching it. | `aws elbv2 describe-load-balancers` |
| An EBS volume | Retained by a `Retain` reclaim policy, or left behind when a cluster is destroyed before its PVCs | `aws ec2 describe-volumes --filters Name=status,Values=available` |
| A NAT Gateway with its Elastic IP | Both bill hourly. A failed `network` destroy leaves them. | `aws ec2 describe-nat-gateways`, `aws ec2 describe-addresses` |

## Rebuilding afterwards

Follow [reproduce.md](reproduce.md). Two things will differ:

- A new NLB hostname, which must be written into `infra/terraform/iam/dns-demo.tf`. It is hardcoded; see [../lessons.md](../lessons.md).
- New subnet IDs, which must be written into `k8s/platform/traefik/values-public.yaml`.

The `postgres-credentials` Secret must also be recreated by hand, and the voting data starts empty unless a dump from the pre-teardown step is restored.
