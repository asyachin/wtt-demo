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

## Safety rules

This procedure deletes infrastructure. The AWS account and the cluster may contain resources that do not belong to this project, so every destructive command below is scoped, and every scoped command is preceded by a read-only command that shows exactly what will be affected.

| Rule | Reason |
|---|---|
| Assert account, region and cluster context before anything else | A teardown run against the wrong account or region is unrecoverable |
| Never use `--all` on a destructive `kubectl` command | `delete pvc --all` would destroy any volume a future workload added to the namespace |
| Never infer ownership from "it is in this account" | Filter by `Project=wtt-demo`, by the cluster tag, by VPC ID, or by an ID captured beforehand |
| Capture resource IDs before deleting, then delete by ID | An ID captured from the live object is unambiguous; a query repeated later may return something else |
| Read before you delete | Every `delete` below is paired with the `describe` or `get` that justifies it |

Verification commands check that **no resource belonging to this project** remains. They do not assert that the account is empty.

## Before starting

### Preflight — assert the target, and stop if it is wrong

```bash
EXPECTED_ACCOUNT=899088266068          # replace for another account
EXPECTED_REGION=eu-north-1
EXPECTED_CLUSTER=wtt-demo-eks
PROJECT_TAG=wtt-demo

export AWS_REGION="$EXPECTED_REGION"

ACTUAL_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
if [ "$ACTUAL_ACCOUNT" != "$EXPECTED_ACCOUNT" ]; then
  echo "ABORT: account $ACTUAL_ACCOUNT is not $EXPECTED_ACCOUNT"; return 2>/dev/null || exit 1
fi

aws eks update-kubeconfig --region "$EXPECTED_REGION" --name "$EXPECTED_CLUSTER"
ACTUAL_CTX=$(kubectl config current-context)
case "$ACTUAL_CTX" in
  *"$EXPECTED_CLUSTER"*) : ;;
  *) echo "ABORT: context $ACTUAL_CTX is not $EXPECTED_CLUSTER"; return 2>/dev/null || exit 1 ;;
esac

echo "OK: account $ACTUAL_ACCOUNT, region $EXPECTED_REGION, context $ACTUAL_CTX"
```

Do not continue past a failed assertion. Everything below assumes these four variables are set in the shell.

### Capture the IDs that will be deleted

Deletion later refers to these captured values, never to a repeated broad query.

```bash
# The VPC that scopes most of the AWS resources
VPC_ID=$(aws ec2 describe-vpcs \
  --filters "Name=tag:Project,Values=$PROJECT_TAG" \
  --query 'Vpcs[].VpcId' --output text)
echo "VPC_ID=$VPC_ID"

# The NLB, identified by the VPC it sits in
NLB_ARN=$(aws elbv2 describe-load-balancers \
  --query "LoadBalancers[?VpcId=='$VPC_ID'].LoadBalancerArn" --output text)
NLB_DNS=$(kubectl -n traefik get svc traefik \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)
echo "NLB_ARN=$NLB_ARN"
echo "NLB_DNS=$NLB_DNS"

# The PostgreSQL claim, its PersistentVolume, and the EBS volume behind it
PVC_NAME=$(kubectl -n vote-dev get pvc -o jsonpath='{.items[0].metadata.name}')
PV_NAME=$(kubectl -n vote-dev get pvc "$PVC_NAME" -o jsonpath='{.spec.volumeName}')
EBS_VOL=$(kubectl get pv "$PV_NAME" -o jsonpath='{.spec.csi.volumeHandle}')
RECLAIM=$(kubectl get pv "$PV_NAME" -o jsonpath='{.spec.persistentVolumeReclaimPolicy}')
echo "PVC=$PVC_NAME  PV=$PV_NAME  EBS=$EBS_VOL  reclaim=$RECLAIM"

# NAT gateways and addresses, scoped to the VPC
aws ec2 describe-nat-gateways \
  --filter "Name=vpc-id,Values=$VPC_ID" "Name=state,Values=available,pending" \
  --query 'NatGateways[].{Id:NatGatewayId,Eip:NatGatewayAddresses[0].AllocationId}' --output table
```

Write these values down outside the shell. If a session is lost mid-teardown, they are how the remaining resources are found. `EBS_VOL` in particular cannot be recovered once the PersistentVolume object is gone.

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
# Read first: this is the release and the Service that own the NLB
helm list -n traefik
kubectl -n traefik get svc traefik

helm uninstall traefik -n traefik

# Or, if only the load balancer should go:
# kubectl -n traefik delete svc traefik
```

The NLB deletion is asynchronous. Wait for the load balancer **in this project's VPC** to disappear, not for the account to empty:

```bash
for i in $(seq 1 30); do
  n=$(aws elbv2 describe-load-balancers \
        --query "length(LoadBalancers[?VpcId=='$VPC_ID'])" --output text)
  echo "load balancers in $VPC_ID: $n"
  [ "$n" = "0" ] && break
  sleep 10
done
```

Confirm before continuing:

```bash
aws elbv2 describe-load-balancers \
  --query "LoadBalancers[?VpcId=='$VPC_ID'].{Name:LoadBalancerName,State:State.Code}" --output table
```

This must return nothing. If a load balancer remains, delete it explicitly **by the ARN captured in preflight** before destroying the cluster, or it becomes an orphan with no controller to clean it up:

```bash
# Only if the wait loop above timed out, and only for the captured ARN
# aws elbv2 delete-load-balancer --load-balancer-arn "$NLB_ARN"
```

Uninstalling Traefik also removes the `GatewayClass` and `Gateway` it created, so the public demonstration is down from this point.

## Step 2 — Remove the DNS record

```bash
cd infra/terraform/iam
terraform destroy -target=aws_route53_record.wtt_demo
```

Removing the record before the NLB is gone prevents a window where DNS points at a load balancer that no longer exists. Order here is a courtesy rather than a cost matter.

The hosted zone itself is not managed by this project and is not destroyed.

## Step 3 — Delete the persistent volumes

Decide deliberately, because the outcome differs by reclaim policy. The values were captured in preflight.

```bash
echo "PVC=$PVC_NAME  PV=$PV_NAME  EBS=$EBS_VOL  reclaim=$RECLAIM"
```

| Policy | Deleting the PVC |
|---|---|
| `Delete` — the current setting | The EBS volume is destroyed. **All voting data is lost, irreversibly.** |
| `Retain` — after [Block 06](../blocks/06-data-durability.md) | The volume survives and **keeps billing** until deleted explicitly by ID |

List what exists before deleting anything, and delete by name rather than with `--all`:

```bash
# Read: every claim in the namespace, so nothing unexpected is removed
kubectl -n vote-dev get pvc -o custom-columns=\
'NAME:.metadata.name,PV:.spec.volumeName,SIZE:.spec.resources.requests.storage,SC:.spec.storageClassName'

kubectl -n vote-dev delete statefulset postgres
kubectl -n vote-dev delete pvc "$PVC_NAME"        # by name, never --all
```

`--all` is avoided deliberately: if a future workload has added a claim to this namespace, `--all` would destroy its volume too.

With `reclaimPolicy: Retain`, the PersistentVolume and the EBS volume survive and keep billing. Remove them explicitly, **using the volume ID captured in preflight**:

```bash
kubectl get pv "$PV_NAME" -o custom-columns=\
'NAME:.metadata.name,STATUS:.status.phase,RECLAIM:.spec.persistentVolumeReclaimPolicy,EBS:.spec.csi.volumeHandle'

# Confirm the captured ID, its size and its tags before deleting it
aws ec2 describe-volumes --volume-ids "$EBS_VOL" \
  --query 'Volumes[].{Id:VolumeId,Size:Size,State:State,AZ:AvailabilityZone,Tags:Tags}'

# Then, only if the output above is the expected volume:
# kubectl delete pv "$PV_NAME"
# aws ec2 delete-volume --volume-id "$EBS_VOL"
```

An available, unattached EBS volume is the resource most often forgotten. It is cheap, which is exactly why nobody notices it for months.

Do not search for orphaned volumes with an unfiltered `describe-volumes` and delete what it returns. In a shared account that query also lists volumes belonging to other workloads. Use the captured ID, or filter by the cluster tag:

```bash
aws ec2 describe-volumes \
  --filters "Name=tag:kubernetes.io/cluster/$EXPECTED_CLUSTER,Values=owned" \
  --query 'Volumes[].{Id:VolumeId,Size:Size,State:State}' --output table
```

That tag is applied by the EBS CSI driver only when configured to do so, so it may return nothing even when a volume exists. Treat the captured ID as authoritative and this query as a cross-check.

## Step 4 — Optional: remove remaining Kubernetes resources

Not strictly necessary, since destroying the cluster removes everything in it. Worth doing if the cluster might be kept.

Deleting by manifest file is the safe form: it removes exactly the objects this project declares, and nothing else that may share the namespaces.

```bash
kubectl delete -f k8s/apps/dev/ --ignore-not-found
kubectl delete -f k8s/platform/cert-manager/ --ignore-not-found
helm uninstall cert-manager -n cert-manager

# The namespaces last, and only if nothing else lives in them
kubectl -n vote-dev get all
kubectl -n vote-prod get all
kubectl delete -f k8s/base/namespaces.yaml --ignore-not-found
```

Deleting a namespace deletes everything inside it, including objects this project never created. The two `get all` calls above are there so that is a decision rather than a surprise.

Note that `k8s/base/namespaces.yaml` declares both `vote-dev` and `vote-prod`. The `postgres-credentials` Secret is destroyed with `vote-dev`, and it exists nowhere else; see [../decisions/0020-manual-postgres-secret.md](../decisions/0020-manual-postgres-secret.md).

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
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'NetworkInterfaces[].{Id:NetworkInterfaceId,Desc:Description,Status:Status,Owner:RequesterId}' \
  --output table
```

Scoped to the captured `VPC_ID`, so it cannot report interfaces from another VPC. Identify what holds the interface, remove that, then retry the destroy. Never force-delete Terraform state to make an error disappear: the resource would keep billing with nothing tracking it.

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

## Step 7 — Verify this project's resources are gone

Each query is scoped to this project. A result means something belonging to `wtt-demo` survives. **These checks do not assert that the account is empty**, and they must not be rewritten to do so: the account may hold unrelated resources that are none of this project's business.

```bash
# The cluster, by name
aws eks list-clusters --region "$EXPECTED_REGION" \
  --query "clusters[?@=='$EXPECTED_CLUSTER']"

# Instances, by the tag EKS applies to managed node groups
aws ec2 describe-instances --region "$EXPECTED_REGION" \
  --filters "Name=tag:eks:cluster-name,Values=$EXPECTED_CLUSTER" \
            "Name=instance-state-name,Values=running,pending,stopping,stopped" \
  --query 'Reservations[].Instances[].{Id:InstanceId,State:State.Name}'

# The VPC, by the Project tag applied through Terraform default_tags
aws ec2 describe-vpcs --region "$EXPECTED_REGION" \
  --filters "Name=tag:Project,Values=$PROJECT_TAG" \
  --query 'Vpcs[].VpcId'

# NAT gateways and Elastic IPs, by the same tag
aws ec2 describe-nat-gateways --region "$EXPECTED_REGION" \
  --filter "Name=tag:Project,Values=$PROJECT_TAG" \
           "Name=state,Values=available,pending,deleting" \
  --query 'NatGateways[].{Id:NatGatewayId,State:State}'

aws ec2 describe-addresses --region "$EXPECTED_REGION" \
  --filters "Name=tag:Project,Values=$PROJECT_TAG" \
  --query 'Addresses[].{Ip:PublicIp,Alloc:AllocationId,Assoc:AssociationId}'

# The EBS volume, by the ID captured in preflight
[ -n "$EBS_VOL" ] && aws ec2 describe-volumes --region "$EXPECTED_REGION" \
  --volume-ids "$EBS_VOL" --query 'Volumes[].{Id:VolumeId,State:State}' 2>/dev/null \
  || echo "volume $EBS_VOL no longer exists"
```

An unassociated Elastic IP bills even though it does nothing, which is why `describe-addresses` is in the list.

### If the VPC is already gone

Once the VPC is deleted, `VPC_ID` can no longer be used to find a surviving load balancer. Fall back to the DNS name captured in preflight:

```bash
[ -n "$NLB_DNS" ] && aws elbv2 describe-load-balancers --region "$EXPECTED_REGION" \
  --query "LoadBalancers[?DNSName=='$NLB_DNS'].{Name:LoadBalancerName,State:State.Code}" \
  --output table
```

This is the reason preflight records `NLB_DNS` as well as `NLB_ARN`.

### Untagged resources

Tag-based queries only find what Terraform tagged through `default_tags`, which covers the VPC, NAT gateway, Elastic IP and subnets. Resources created by Kubernetes — the NLB and the dynamically provisioned EBS volume — carry Kubernetes tags instead, which is why they are tracked by captured ID rather than by `Project`.

If a resource was created by hand at some point and never tagged, no query here will find it. The only reliable backstop is the cost check below.

### Confirm against billing

The console lags, so check 24 hours later:

```bash
aws ce get-cost-and-usage --region us-east-1 \
  --time-period Start=$(date -u -d yesterday +%F),End=$(date -u +%F) \
  --granularity DAILY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE
```

Compare against the expectation in [../architecture.md](../architecture.md#cost-estimate). Residual charges for EKS, EC2, `ElasticLoadBalancing`, `NatGateway` or EBS mean something survived. Note that other workloads in the account will also appear here, so read the per-service figures rather than the total.

## The three resources most often left behind

| Resource | Why it is missed | How to find it, scoped |
|---|---|---|
| The NLB | Created by Kubernetes, not Terraform. `terraform destroy` reports success without touching it. | While the VPC exists, filter on `VpcId=='$VPC_ID'`. Afterwards, match the `NLB_DNS` captured in preflight. |
| An EBS volume | Retained by a `Retain` reclaim policy, or left behind when a cluster is destroyed before its PVCs | `aws ec2 describe-volumes --volume-ids "$EBS_VOL"`, using the ID captured in preflight. Never an unfiltered listing. |
| A NAT Gateway with its Elastic IP | Both bill hourly. A failed `network` destroy leaves them. | Filter on `Name=tag:Project,Values=$PROJECT_TAG` |

All three are found by an identifier or a tag, never by listing everything in the account and judging by eye. That is the difference between a teardown and an accident.

## Rebuilding afterwards

Follow [reproduce.md](reproduce.md). Two things will differ:

- A new NLB hostname, which must be written into `infra/terraform/iam/dns-demo.tf`. It is hardcoded; see [../lessons.md](../lessons.md).
- New subnet IDs, which must be written into `k8s/platform/traefik/values-public.yaml`.

The `postgres-credentials` Secret must also be recreated by hand, and the voting data starts empty unless a dump from the pre-teardown step is restored.
