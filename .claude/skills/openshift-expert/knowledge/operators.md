# OpenShift Cluster Operators Reference

Detailed troubleshooting guide for core OpenShift cluster operators.

## Operator Dependency Map

Understanding dependencies is critical for root cause analysis:

```
etcd (foundation)
  ├── kube-apiserver
  │   ├── kube-controller-manager
  │   ├── kube-scheduler
  │   └── openshift-apiserver
  │       └── openshift-controller-manager
  │
  ├── dns
  │   └── ingress
  │       └── authentication
  │           └── console
  │
  ├── network
  │   ├── monitoring
  │   └── service-ca
  │
  └── machine-config-operator
      └── machine-api
```

**Rule**: If operator A depends on operator B, and B is degraded, A will likely also degrade.

---

## Core Infrastructure Operators

### etcd

**Purpose**: Distributed key-value store, foundation for cluster state

**Critical**: YES - cluster cannot function without etcd

**Common Issues**:

1. **Quorum Loss**
   - Symptom: `EtcdMembersAvailable = False`
   - Cause: 2+ of 3 etcd members down
   - Impact: Cluster API unavailable, cannot write state
   - Check: `omc/oc get pods -n openshift-etcd`

2. **Disk Performance**
   - Symptom: `EtcdBackendQuotaLowSpace = True`
   - Cause: Slow disk, insufficient IOPS
   - Impact: Degraded performance, writes slow
   - Check: `omc/oc get events -n openshift-etcd | grep Performance`

3. **Certificate Issues**
   - Symptom: `EtcdCertSignerControllerDegraded = True`
   - Cause: Certificate rotation failed
   - Impact: etcd members cannot communicate
   - Check: Certificate expiry in etcd pod logs

**Troubleshooting**:
```bash
# Check operator status
omc/oc get co etcd -o yaml

# Check etcd pods
omc/oc get pods -n openshift-etcd

# Check etcd logs
omc/oc logs -n openshift-etcd etcd-<node-name>

# Check quorum (live only)
oc rsh -n openshift-etcd etcd-<node>
etcdctl member list
etcdctl endpoint health
```

**Dependencies**: None (foundation layer)

---

### kube-apiserver

**Purpose**: Kubernetes API server, entry point for all cluster operations

**Critical**: YES - all cluster operations require API server

**Common Issues**:

1. **API Server Pods Not Ready**
   - Symptom: `APIServerAvailable = False`
   - Cause: Pods crashing, etcd unreachable, certificate issues
   - Impact: No cluster operations possible
   - Check: `omc/oc get pods -n openshift-kube-apiserver`

2. **Connection Failures to etcd**
   - Symptom: Logs show "etcd cluster unavailable"
   - Cause: etcd degraded, network issues, certificate problems
   - Impact: Cannot read/write cluster state
   - Check: etcd operator status first

3. **Authentication Issues**
   - Symptom: All requests return 401 Unauthorized
   - Cause: OAuth configuration issue, ServiceAccount tokens invalid
   - Impact: Users and system components cannot authenticate
   - Check: `omc/oc logs -n openshift-kube-apiserver kube-apiserver-<node>`

**Troubleshooting**:
```bash
# Check operator status
omc/oc get co kube-apiserver -o yaml

# Check pods
omc/oc get pods -n openshift-kube-apiserver

# Check logs for errors
omc/oc logs -n openshift-kube-apiserver kube-apiserver-<node> | grep -E "error|Error|failed"

# Check apiserver configuration
omc/oc get kubeapiserver cluster -o yaml
```

**Dependencies**: etcd

---

### network

**Purpose**: Manages cluster networking (CNI plugin - typically OVN-Kubernetes)

**Critical**: YES - without networking, pods cannot communicate

**Common Issues**:

1. **OVN Pods Not Running**
   - Symptom: `NetworkDegraded = True`
   - Cause: OVN DaemonSet pods failed, node network issues
   - Impact: New pods cannot get IPs, networking broken
   - Check: `omc/oc get pods -n openshift-ovn-kubernetes`

2. **SDN to OVN Migration Issues**
   - Symptom: Pods cannot reach services after migration
   - Cause: Incomplete migration, conflicting network policies
   - Impact: Network connectivity broken
   - Check: `omc/oc get network.operator cluster -o yaml`

3. **Multus CNI Failures**
   - Symptom: Pods with multiple interfaces fail
   - Cause: Multus DaemonSet not running, NetworkAttachmentDefinition invalid
   - Impact: Secondary network interfaces not created
   - Check: `omc/oc get pods -n openshift-multus`

**Troubleshooting**:
```bash
# Check operator
omc/oc get co network -o yaml

# Check OVN pods (most common CNI)
omc/oc get pods -n openshift-ovn-kubernetes

# Check for network policies affecting pods
omc/oc get networkpolicy -A

# Check cluster network configuration
omc/oc get network.config.openshift.io cluster -o yaml
```

**Dependencies**: etcd, kube-apiserver

---

### dns

**Purpose**: CoreDNS for cluster DNS resolution

**Critical**: YES - services cannot be resolved without DNS

**Common Issues**:

1. **CoreDNS Pods Not Running**
   - Symptom: `DNSAvailable = False`
   - Cause: DaemonSet not scheduled, image pull failures
   - Impact: DNS resolution fails cluster-wide
   - Check: `omc/oc get pods -n openshift-dns`

2. **DNS Configuration Corrupted**
   - Symptom: DNS works for some domains but not others
   - Cause: Invalid CoreDNS ConfigMap
   - Impact: Inconsistent DNS behavior
   - Check: `omc/oc get configmap -n openshift-dns dns-default`

3. **NetworkPolicy Blocking DNS**
   - Symptom: Pods cannot resolve DNS
   - Cause: NetworkPolicy in pod namespace blocks port 53
   - Impact: Specific namespace DNS broken
   - Check: `omc/oc get networkpolicy -n <affected-namespace>`

**Troubleshooting**:
```bash
# Check operator
omc/oc get co dns -o yaml

# Check CoreDNS pods
omc/oc get pods -n openshift-dns

# Check DNS logs
omc/oc logs -n openshift-dns dns-default-<id>

# Test DNS (live only)
oc run -it --rm debug --image=ubi8 -- nslookup kubernetes.default.svc.cluster.local
```

**Dependencies**: network

---

## Node Management Operators

### machine-config-operator

**Purpose**: Manages node configuration, OS updates, and MachineConfig reconciliation

**Critical**: YES - nodes cannot be properly configured or updated without MCO

**Common Issues**:

1. **MachineConfig Rendering Failed**
   - Symptom: `RenderingDegraded = True`, "failed to render MachineConfig"
   - Cause: Invalid MachineConfig, conflicting configs, ignition parse error
   - Impact: Cannot apply node configuration changes
   - Check: `omc/oc get machineconfig`, machine-config-controller logs

2. **Node Update Stuck (Draining/Cordoning)**
   - Symptom: `NodeUpdateDegraded = True`, nodes stuck in "SchedulingDisabled"
   - Cause: Pods with PodDisruptionBudget blocking drain, node cannot be drained
   - Impact: OS updates cannot proceed, cluster stuck mid-update
   - Check: `omc/oc get nodes`, `omc/oc get pods -A | grep Evict`

3. **Machine Config Daemon (MCD) Failed**
   - Symptom: Nodes stuck in degraded state, MCD pod CrashLooping
   - Cause: MCD cannot apply config, file conflicts, permission issues
   - Impact: Node configuration out of sync
   - Check: `omc/oc get pods -n openshift-machine-config-operator | grep daemon`

4. **Kubelet Certificate Rotation Issues**
   - Symptom: `KubeletServingCADegraded = True`
   - Cause: Certificate signer unavailable, CSR approval failed
   - Impact: Kubelet cannot communicate securely
   - Check: `omc/oc get csr | grep Pending`

**Troubleshooting**:
```bash
# Check operator status
omc/oc get co machine-config -o yaml

# Check MachineConfigPool status (critical!)
omc/oc get machineconfigpool
# Look for: UPDATED=False, UPDATING=True (stuck), DEGRADED=True

# Check MachineConfigs
omc/oc get machineconfig
omc/oc get machineconfig rendered-worker-<hash> -o yaml

# Check machine-config-controller logs
omc/oc logs -n openshift-machine-config-operator machine-config-controller-<id>

# Check MCD on specific node
omc/oc get pods -n openshift-machine-config-operator -o wide | grep daemon
omc/oc logs -n openshift-machine-config-operator machine-config-daemon-<node>

# Check node status
omc/oc get nodes
omc/oc describe node <node-name> | grep -A 10 "Conditions:"

# Check for stuck drains (live only)
oc adm drain <node> --dry-run  # See what's blocking

# Check CSRs (certificate signing requests)
omc/oc get csr
omc/oc get csr | grep Pending  # Should be approved automatically
```

**MachineConfigPool States**:
- `UPDATED=True` - All nodes have latest config
- `UPDATING=True` - Rolling update in progress
- `DEGRADED=True` - Cannot apply config to some nodes
- `MACHINECOUNT` vs `READYMACHINECOUNT` - Shows progress

**Common MachineConfig Issues**:

| Issue | Symptom | Resolution |
|-------|---------|------------|
| Invalid Ignition | Rendering failed | Fix MachineConfig syntax |
| Conflicting configs | Multiple MCs editing same file | Consolidate configs |
| PDB blocking drain | Node stuck draining | Adjust PodDisruptionBudget |
| MCD crash | Node never updates | Check MCD logs, node disk space |
| CSR not approved | Kubelet cert rotation fails | Approve CSR or check signer |

**Dependencies**: etcd, kube-apiserver

---

### machine-api

**Purpose**: Manages cluster infrastructure (Machines, MachineSets) on cloud providers

**Critical**: High - required for auto-scaling, node replacement, cluster expansion

**Common Issues**:

1. **Machine Stuck in Provisioning**
   - Symptom: Machine phase = "Provisioning" for >15 minutes
   - Cause: Cloud API timeout, quota exceeded, invalid instance type, AMI not found
   - Impact: New nodes never join cluster, cluster cannot scale
   - Check: `omc/oc get machine -n openshift-machine-api`, machine-controller logs

2. **Machine Failed**
   - Symptom: Machine phase = "Failed", never becomes "Running"
   - Cause: Cloud provisioning error, network config invalid, IAM permissions
   - Impact: Cannot add nodes to cluster
   - Check: `omc/oc describe machine <machine> -n openshift-machine-api`

3. **MachineSet Not Scaling**
   - Symptom: Desired replicas != current replicas
   - Cause: Machine creation failed, quota exceeded, no capacity in zone
   - Impact: Auto-scaling broken, cannot meet capacity needs
   - Check: `omc/oc get machineset -n openshift-machine-api`

4. **Cloud Provider Credentials Invalid**
   - Symptom: All machine operations fail with "authentication failed"
   - Cause: Cloud credentials expired, permissions removed, secret deleted
   - Impact: Cannot manage any infrastructure
   - Check: `omc/oc get secret -n openshift-machine-api | grep credentials`

5. **Node Never Joins After Machine Running**
   - Symptom: Machine phase = "Running", but node not in `oc get nodes`
   - Cause: Ignition failure, network connectivity, kubelet not started
   - Impact: VM exists but not usable by cluster
   - Check: SSH to node (if possible), check cloud console for VM

**Troubleshooting**:
```bash
# Check operator status
omc/oc get co machine-api -o yaml

# Check Machines
omc/oc get machine -n openshift-machine-api
# Look for: Phase (Provisioning/Provisioned/Running/Failed/Deleting)

# Check MachineSets
omc/oc get machineset -n openshift-machine-api
# DESIRED vs CURRENT vs READY shows scaling status

# Describe specific machine for errors
omc/oc describe machine <machine-name> -n openshift-machine-api
# Look at Events section for provisioning errors

# Check machine-api-controllers logs
omc/oc logs -n openshift-machine-api machine-api-controllers-<id>

# Check machine-api-operator logs
omc/oc logs -n openshift-machine-api machine-api-operator-<id>

# Check cloud provider credentials
omc/oc get secret -n openshift-machine-api
omc/oc get secret <cloud>-cloud-credentials -n openshift-machine-api -o yaml

# Check cluster autoscaler (if installed)
omc/oc get clusterautoscaler
omc/oc get machineautoscaler -n openshift-machine-api

# Cross-reference with nodes
omc/oc get nodes
# Machine exists but node doesn't = provisioning issue
```

**Machine Lifecycle States**:

1. **Provisioning** (0-10 min)
   - Cloud API called to create VM
   - Instance launching
   - If stuck: Check cloud quotas, API errors in machine-controller logs

2. **Provisioned** (brief)
   - VM created, starting up
   - Ignition running
   - If stuck: Ignition failure, check cloud console

3. **Running** (steady state)
   - VM running, node joined cluster
   - Healthy state
   - If node not in `oc get nodes`: Network/kubelet issue

4. **Failed** (terminal)
   - Cloud provisioning failed
   - Check machine description Events
   - Delete machine to retry

5. **Deleting** (0-5 min)
   - VM terminating
   - If stuck: Cloud API issue, check machine-controller logs

**Cloud-Specific Issues**:

**AWS**:
- "InsufficientInstanceCapacity" - No capacity in AZ, try different zone
- "UnauthorizedOperation" - IAM permissions missing
- "InvalidAMIID.NotFound" - AMI deleted or wrong region

**Azure**:
- "QuotaExceeded" - Subscription quota hit
- "AllocationFailed" - No capacity in region
- "InvalidParameter" - Network config wrong (subnet, NSG)

**GCP**:
- "ZONE_RESOURCE_POOL_EXHAUSTED" - No capacity in zone
- "QUOTA_EXCEEDED" - Project quota hit
- "INVALID_FIELD_VALUE" - Machine type or image invalid

**vSphere**:
- "Session not authenticated" - vCenter credentials expired
- "Template not found" - RHCOS template missing/deleted
- "Network not found" - Port group doesn't exist

**Common Resolutions**:

| Issue | Immediate Fix | Long-term Solution |
|-------|---------------|---------------------|
| Quota exceeded | Request quota increase | Implement capacity planning |
| Invalid instance type | Update MachineSet with valid type | Document supported types |
| AMI not found | Update to valid AMI ID | Automate AMI discovery |
| Network config wrong | Fix subnet/SG/NSG in MachineSet | Validate network config in CI |
| Ignition failure | Fix MachineConfig or cloud-init | Test configs before rollout |

**Dependencies**: kube-apiserver, machine-config-operator (for node config)

**Integration with machine-config-operator**:
- **machine-api** creates the VM and joins it to cluster
- **machine-config-operator** configures the OS and applies MachineConfigs
- Both must work together for successful node provisioning

---

## Ingress & Authentication

### ingress

**Purpose**: Router/Ingress controller for external traffic

**Critical**: High - external services unreachable without ingress

**Common Issues**:

1. **Router Pods Not Running**
   - Symptom: `IngressControllerAvailable = False`
   - Cause: Router pods crashed, insufficient node capacity
   - Impact: Routes return 503, external access broken
   - Check: `omc/oc get pods -n openshift-ingress`

2. **DNS Not Configured**
   - Symptom: Routes work by IP but not by hostname
   - Cause: DNS not pointing to router load balancer
   - Impact: Hostnames don't resolve
   - Check: IngressController status for router-default

3. **Certificate Issues**
   - Symptom: TLS routes fail with certificate errors
   - Cause: Default certificate invalid, custom cert expired
   - Impact: HTTPS routes broken
   - Check: `omc/oc get ingresscontroller -n openshift-ingress-operator -o yaml`

**Troubleshooting**:
```bash
# Check operator
omc/oc get co ingress -o yaml

# Check IngressController
omc/oc get ingresscontroller -n openshift-ingress-operator

# Check router pods
omc/oc get pods -n openshift-ingress

# Check router logs
omc/oc logs -n openshift-ingress router-default-<id>

# Check specific route
omc/oc get route -n <namespace>
omc/oc describe route <route-name> -n <namespace>
```

**Dependencies**: dns, network

---

### authentication

**Purpose**: OAuth server for user authentication

**Critical**: High - users cannot log in without authentication

**Common Issues**:

1. **OAuth Server Not Available**
   - Symptom: `OAuthServerDeploymentAvailable = False`
   - Cause: OAuth pods crashed, dependency failure
   - Impact: Cannot log in to console or CLI
   - Check: `omc/oc get pods -n openshift-authentication`

2. **Identity Provider Failure**
   - Symptom: Login fails with "identity provider error"
   - Cause: LDAP unreachable, OAuth provider down
   - Impact: Users cannot authenticate
   - Check: `omc/oc get oauth cluster -o yaml`

3. **ServiceAccount Token Issues**
   - Symptom: Pods cannot authenticate to API server
   - Cause: Token expiration, signing key rotation failed
   - Impact: Workloads cannot access Kubernetes API
   - Check: Operator logs for token controller errors

**Troubleshooting**:
```bash
# Check operator
omc/oc get co authentication -o yaml

# Check OAuth server pods
omc/oc get pods -n openshift-authentication

# Check OAuth configuration
omc/oc get oauth cluster -o yaml

# Check identity provider connectivity (from oauth pod logs)
omc/oc logs -n openshift-authentication oauth-openshift-<id> | grep -i "identity provider"
```

**Dependencies**: ingress, dns

---

## Storage

### storage

**Purpose**: Manages storage operator and CSI drivers

**Critical**: High - persistent volumes require storage

**Common Issues**:

1. **CSI Driver Not Available**
   - Symptom: `StorageDriverHealthCheckControllerAvailable = False`
   - Cause: CSI controller pods down, CSI node DaemonSet failed
   - Impact: Cannot provision new volumes
   - Check: `omc/oc get pods -n openshift-cluster-csi-drivers`

2. **Default StorageClass Missing**
   - Symptom: PVCs stay pending with "no StorageClass"
   - Cause: StorageClass not created or deleted
   - Impact: Dynamic provisioning fails
   - Check: `omc/oc get storageclass`

3. **Cloud Provider API Failures**
   - Symptom: Volume provisioning times out
   - Cause: Cloud API slow/unavailable, quota exceeded
   - Impact: PVCs stuck in pending
   - Check: CSI driver logs for cloud API errors

**Troubleshooting**:
```bash
# Check operator
omc/oc get co storage -o yaml

# Check CSI driver pods
omc/oc get pods -n openshift-cluster-csi-drivers

# Check available StorageClasses
omc/oc get storageclass

# Check CSI driver logs
omc/oc logs -n openshift-cluster-csi-drivers <csi-driver-pod>

# Check PVC issues
omc/oc get pvc -A | grep Pending
```

**Dependencies**: kube-apiserver

---

### image-registry

**Purpose**: Internal image registry for builds and imagestreams

**Critical**: Medium - required for builds, not for deployments

**Common Issues**:

1. **Storage Not Configured**
   - Symptom: `Available = False`, "storage not configured"
   - Cause: PVC not created, StorageClass missing
   - Impact: Registry cannot start
   - Check: `omc/oc get configs.imageregistry.operator.openshift.io cluster -o yaml`

2. **Registry Pod Not Running**
   - Symptom: Image pushes fail
   - Cause: Registry deployment failed, storage mount issues
   - Impact: Cannot push images to internal registry
   - Check: `omc/oc get pods -n openshift-image-registry`

3. **Route Not Exposed**
   - Symptom: External push fails
   - Cause: Registry route not created
   - Impact: Cannot push from outside cluster
   - Check: `omc/oc get route -n openshift-image-registry`

**Troubleshooting**:
```bash
# Check operator
omc/oc get co image-registry -o yaml

# Check registry configuration
omc/oc get configs.imageregistry.operator.openshift.io cluster -o yaml

# Check registry pods
omc/oc get pods -n openshift-image-registry

# Check PVC
omc/oc get pvc -n openshift-image-registry

# Check registry logs
omc/oc logs -n openshift-image-registry image-registry-<id>
```

**Dependencies**: storage

---

## Monitoring & Logging

### monitoring

**Purpose**: Prometheus, Alertmanager, metrics collection

**Critical**: Medium - needed for monitoring, not core functionality

**Common Issues**:

1. **Prometheus Operator Failed**
   - Symptom: `PrometheusOperatorDegraded = True`
   - Cause: Operator cannot reconcile Prometheus
   - Impact: No metrics collected
   - Check: `omc/oc logs -n openshift-monitoring prometheus-operator-<id>`

2. **Storage Issues**
   - Symptom: Prometheus pod pending or crashing
   - Cause: PVC not bound, volume full
   - Impact: Cannot persist metrics
   - Check: `omc/oc get pvc -n openshift-monitoring`

3. **High Cardinality Metrics**
   - Symptom: Prometheus OOMKilled
   - Cause: Too many time series, labels explosion
   - Impact: Monitoring unavailable
   - Check: Prometheus pod memory usage and limits

**Troubleshooting**:
```bash
# Check operator
omc/oc get co monitoring -o yaml

# Check monitoring pods
omc/oc get pods -n openshift-monitoring

# Check Prometheus configuration
omc/oc get prometheus -n openshift-monitoring k8s -o yaml

# Check PVCs
omc/oc get pvc -n openshift-monitoring

# Check for alerting rules firing
omc/oc get prometheusrule -n openshift-monitoring
```

**Dependencies**: storage (for persistence)

---

## Cluster Services

### console

**Purpose**: Web console UI for cluster management

**Critical**: Low - CLI access still works if console down

**Common Issues**:

1. **Console Deployment Not Available**
   - Symptom: `ConsoleDeploymentAvailable = False`
   - Cause: Console pods crashed, OAuth issues
   - Impact: Web UI inaccessible
   - Check: `omc/oc get pods -n openshift-console`

2. **Authentication Failure**
   - Symptom: Console loads but login fails
   - Cause: authentication operator degraded
   - Impact: Cannot log in to console
   - Check: authentication operator status first

3. **Route Issues**
   - Symptom: Console URL returns 503
   - Cause: Route not created, ingress controller issues
   - Impact: Cannot access console
   - Check: `omc/oc get route -n openshift-console`

**Troubleshooting**:
```bash
# Check operator
omc/oc get co console -o yaml

# Check console pods
omc/oc get pods -n openshift-console

# Check console route
omc/oc get route console -n openshift-console

# Check console logs
omc/oc logs -n openshift-console console-<id>
```

**Dependencies**: authentication, ingress

---

### operator-lifecycle-manager (OLM)

**Purpose**: Manages operator installation and lifecycle

**Critical**: Medium - required for operator installation, not runtime

**Common Issues**:

1. **OLM Pods Not Running**
   - Symptom: Cannot install operators
   - Cause: olm-operator or catalog-operator crashed
   - Impact: Operator installation fails
   - Check: `omc/oc get pods -n openshift-operator-lifecycle-manager`

2. **CatalogSource Not Ready**
   - Symptom: Operators don't appear in console
   - Cause: CatalogSource pod failed, image pull issues
   - Impact: Cannot browse/install operators
   - Check: `omc/oc get catalogsource -n openshift-marketplace`

3. **Subscription Issues**
   - Symptom: Operator stuck in "Installing"
   - Cause: InstallPlan not approved, CSV invalid
   - Impact: Operator never becomes ready
   - Check: `omc/oc get subscription,installplan,csv -n <namespace>`

**Troubleshooting**:
```bash
# Check OLM pods
omc/oc get pods -n openshift-operator-lifecycle-manager

# Check CatalogSources
omc/oc get catalogsource -n openshift-marketplace
omc/oc get pods -n openshift-marketplace

# Check subscriptions
omc/oc get subscription -A

# Check InstallPlans
omc/oc get installplan -A

# Check ClusterServiceVersion (CSV)
omc/oc get csv -A
```

**Dependencies**: kube-apiserver, image-registry (for operator images)

---

## Quick Reference: Degraded Operator Workflow

```
Operator Degraded
├─ 1. Check operator status
│  └─ omc/oc get co <operator> -o yaml
│     └─ Look at status.conditions for specific reason
│
├─ 2. Check operator pod
│  └─ omc/oc get pods -n openshift-<operator-namespace>
│     ├─ Not running → Check pod events
│     └─ Running → Check pod logs
│
├─ 3. Check operator logs
│  └─ omc/oc logs -n openshift-<operator-namespace> <pod>
│     └─ Look for reconciliation errors
│
├─ 4. Check resources operator manages
│  └─ omc/oc get <resource-type> -n <namespace>
│     └─ Are managed resources healthy?
│
└─ 5. Check dependencies
   └─ Is there a dependent operator also degraded?
      └─ Fix dependencies first (bottom-up)
```

## Operator Health Check Commands

**Quick health check script**:
```bash
# Check all cluster operators
omc/oc get co

# Find degraded operators
omc/oc get co | grep -v "True.*False.*False"

# Check specific operator details
for op in $(omc/oc get co -o name); do
  echo "=== $op ==="
  omc/oc get $op -o jsonpath='{range .status.conditions[*]}{.type}{"\t"}{.status}{"\t"}{.message}{"\n"}{end}'
done
```

**Must-gather includes operator data**:
- All operator pod logs
- All operator configurations
- Operator-managed resource status
- Events related to operators