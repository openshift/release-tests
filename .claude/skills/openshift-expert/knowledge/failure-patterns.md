# OpenShift Failure Patterns Catalog

Comprehensive catalog of common failure signatures with root causes, troubleshooting steps, and resolutions.

## Infrastructure Failures

### ImagePullBackOff / ErrImagePull

**Signature Patterns**:
```
Failed to pull image "...": rpc error: code = Unknown desc = Error reading manifest
ErrImagePull
ImagePullBackOff
Back-off pulling image "..."
```

**Root Causes by Category**:

1. **Registry Authentication Failure** (40% of cases)
   - Missing pull secret in namespace
   - Invalid credentials in pull secret
   - Expired registry token
   - Docker Hub rate limiting (429 Too Many Requests)

2. **Image Does Not Exist** (30% of cases)
   - Typo in image name or tag
   - Image not yet published to registry
   - Wrong registry URL
   - Tag deleted from registry

3. **Network Connectivity** (20% of cases)
   - Egress NetworkPolicy blocking registry
   - Proxy misconfiguration
   - DNS resolution failure for registry
   - Firewall blocking registry port

4. **Registry Issues** (10% of cases)
   - Registry temporarily unavailable
   - Registry storage quota exceeded
   - Certificate validation failure

**Troubleshooting Steps**:

```bash
# Step 1: Check pod events
omc/oc describe pod <pod-name> -n <namespace>
# Look for: "Failed to pull image", "unauthorized", "not found"

# Step 2: Verify pull secret exists
omc/oc get secret -n <namespace> | grep pull-secret
omc/oc get secret <pull-secret> -n <namespace> -o yaml

# Step 3: Check image name in pod spec
omc/oc get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].image}'

# Step 4: Test registry connectivity (live cluster only)
oc debug node/<node-name>
chroot /host
podman pull <image-url>
```

**Resolution Strategies**:

| Root Cause | Immediate Action | Long-term Fix |
|------------|------------------|---------------|
| Missing pull secret | Add pull secret to namespace | Automate secret propagation |
| Invalid credentials | Update secret with valid creds | Use registry auth webhook |
| Image doesn't exist | Verify correct image name/tag | CI validation of image refs |
| Rate limiting | Use authenticated registry access | Mirror images to internal registry |
| Network blocking | Check NetworkPolicies, allow egress | Document required egress rules |

---

### CrashLoopBackOff

**Signature Patterns**:
```
Back-off restarting failed container
CrashLoopBackOff
Last State: Terminated
  Reason: Error
  Exit Code: 1
```

**Root Causes by Category**:

1. **Application Crash** (50% of cases)
   - Panic/exception on startup
   - Invalid configuration file
   - Missing environment variable
   - Cannot bind to port (permission or already in use)

2. **Resource Limits** (25% of cases)
   - OOMKilled (out of memory)
   - CPU throttling causing startup timeout
   - Disk quota exceeded

3. **Dependency Failure** (20% of cases)
   - Cannot connect to database/service
   - Missing ConfigMap or Secret
   - Volume mount failure
   - Required external service unavailable

4. **Container Image Issues** (5% of cases)
   - Wrong entrypoint/command
   - Missing binary in image
   - File permission issues

**Troubleshooting Steps**:

```bash
# Step 1: Check container exit reason
omc/oc get pod <pod-name> -n <namespace> -o jsonpath='{.status.containerStatuses[*].state}'
omc/oc get pod <pod-name> -n <namespace> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}'

# Step 2: Get logs from crashed container
omc/oc logs <pod-name> -n <namespace>
omc/oc logs <pod-name> -n <namespace> --previous  # Most important!

# Step 3: Check resource limits and requests
omc/oc describe pod <pod-name> -n <namespace> | grep -A 5 "Limits"
omc/oc describe pod <pod-name> -n <namespace> | grep -A 5 "Requests"

# Step 4: Check events for OOMKilled
omc/oc get events -n <namespace> | grep <pod-name> | grep OOMKilled

# Step 5: Verify dependencies (ConfigMaps, Secrets, Services)
omc/oc get configmap -n <namespace>
omc/oc get secret -n <namespace>
omc/oc get svc -n <namespace>
```

**Exit Code Meanings**:
- `Exit Code 0`: Clean exit (shouldn't crash loop)
- `Exit Code 1`: Generic application error
- `Exit Code 137`: OOMKilled (killed by OOM killer)
- `Exit Code 139`: Segmentation fault
- `Exit Code 143`: Terminated (SIGTERM)

**Resolution Strategies**:

| Root Cause | Immediate Action | Long-term Fix |
|------------|------------------|---------------|
| Application crash | Check --previous logs for error | Fix application bug |
| OOMKilled | Increase memory limit | Optimize app memory usage |
| Missing dependency | Verify ConfigMap/Secret exists | Add startup dependency checks |
| Config error | Fix invalid config values | Add config validation |
| Permission issue | Adjust SCC or file permissions | Use non-root container |

---

### Pending Pods (FailedScheduling)

**Signature Patterns**:
```
0/3 nodes are available: 3 Insufficient cpu
0/3 nodes are available: 3 Insufficient memory
0/3 nodes are available: 3 node(s) had taint {key: value}
pod didn't trigger scale-up: 2 node(s) had volume node affinity conflict
```

**Root Causes by Category**:

1. **Insufficient Resources** (60% of cases)
   - Not enough CPU on any node
   - Not enough memory on any node
   - Too many pods on nodes (pod limit reached)

2. **Node Selector / Affinity** (20% of cases)
   - No nodes match nodeSelector
   - Node affinity rules not satisfied
   - Anti-affinity preventing scheduling

3. **Taints and Tolerations** (15% of cases)
   - Nodes have taints, pod lacks tolerations
   - NoSchedule taint on all eligible nodes

4. **PVC Not Bound** (5% of cases)
   - Waiting for PVC to be provisioned
   - Volume zone affinity conflict
   - Volume not available on selected node

**Troubleshooting Steps**:

```bash
# Step 1: Check pod events
omc/oc describe pod <pod-name> -n <namespace>
# Look for: "FailedScheduling" events with reason

# Step 2: Check node capacity
omc/oc get nodes
omc/oc describe nodes | grep -A 5 "Allocated resources"

# Step 3: Check for taints
omc/oc describe nodes | grep -A 3 "Taints:"

# Step 4: Check pod resource requests
omc/oc get pod <pod-name> -n <namespace> -o yaml | grep -A 5 "resources:"

# Step 5: Check PVC status if volumes involved
omc/oc get pvc -n <namespace>

# Step 6: Check node selectors and affinity
omc/oc get pod <pod-name> -n <namespace> -o yaml | grep -A 10 "nodeSelector\|affinity"
```

**Resolution Strategies**:

| Root Cause | Immediate Action | Long-term Fix |
|------------|------------------|---------------|
| Insufficient CPU/memory | Scale cluster (add nodes) | Right-size pod requests |
| Node selector mismatch | Fix nodeSelector or label nodes | Use node affinity instead |
| Taint blocking | Add toleration to pod | Review taint necessity |
| PVC pending | Check storage provisioner | Ensure StorageClass exists |
| Pod limit reached | Increase max pods per node | Consolidate workloads |

---

## Operator Failures

### ClusterOperator Degraded

**Signature Patterns**:
```
clusteroperator/authentication is degraded because OAuthServerDeploymentDegraded
clusteroperator/ingress is degraded because IngressControllerDegraded
clusteroperator/monitoring is degraded because UpdatingPrometheusOperatorFailed
```

**Common Degraded Operators and Causes**:

#### authentication
- **OAuth server deployment not available**
  - OAuth pods crashing
  - Service account token expired
  - Certificate issues

- **Identity provider configuration invalid**
  - LDAP connection failure
  - OAuth provider unreachable
  - Certificate validation failure

**Check**:
```bash
omc/oc get co authentication -o yaml
omc/oc get pods -n openshift-authentication
omc/oc logs -n openshift-authentication oauth-openshift-<id>
omc/oc get oauth cluster -o yaml
```

#### ingress
- **IngressController not available**
  - Router pods not running
  - DNS issues preventing route updates
  - Certificate problems

- **Default ingress controller missing**
  - IngressController CR deleted
  - Operator cannot reconcile

**Check**:
```bash
omc/oc get co ingress -o yaml
omc/oc get pods -n openshift-ingress
omc/oc get ingresscontroller -n openshift-ingress-operator
omc/oc logs -n openshift-ingress router-default-<id>
```

#### image-registry
- **Storage not provisioned**
  - PVC pending
  - StorageClass missing
  - CSI driver unavailable

- **Registry deployment not ready**
  - Registry pod crashing
  - Cannot mount storage
  - Configuration invalid

**Check**:
```bash
omc/oc get co image-registry -o yaml
omc/oc get config.imageregistry.operator.openshift.io/cluster -o yaml
omc/oc get pods -n openshift-image-registry
omc/oc get pvc -n openshift-image-registry
```

#### monitoring
- **Prometheus operator failing**
  - Cannot update Prometheus
  - Configuration invalid
  - Storage issues

- **Alert manager issues**
  - Alert manager pods not ready
  - Configuration rejected

**Check**:
```bash
omc/oc get co monitoring -o yaml
omc/oc get pods -n openshift-monitoring
omc/oc logs -n openshift-monitoring prometheus-operator-<id>
omc/oc get prometheus -n openshift-monitoring
```

**Resolution Framework**:

1. **Get operator status**: `omc/oc get co <name> -o yaml`
2. **Check conditions**: Look at `status.conditions` for specific degraded reason
3. **Check operator pod**: `omc/oc get pods -n openshift-<operator-namespace>`
4. **Check operator logs**: `omc/oc logs -n openshift-<operator-namespace> <pod>`
5. **Check managed resources**: Check resources that operator manages
6. **Check dependencies**: Is a dependent operator also degraded?

---

## Networking Failures

### DNS Resolution Failures

**Signature Patterns**:
```
dial tcp: lookup <service>.<namespace>.svc.cluster.local: no such host
DNS lookup failed
lookup <hostname> on 172.30.0.10:53: no such host
name resolution failed
```

**Root Causes**:

1. **CoreDNS Not Running** (40%)
   - DNS operator degraded
   - CoreDNS pods crashed
   - DNS DaemonSet not scheduled

2. **NetworkPolicy Blocking DNS** (30%)
   - Egress policy denying port 53
   - No DNS server in allowed list

3. **Service Misconfiguration** (20%)
   - Service name typo
   - Service in different namespace
   - Service endpoints not ready

4. **DNS Configuration Error** (10%)
   - Invalid DNS search domains
   - Corrupted CoreDNS ConfigMap

**Troubleshooting Steps**:

```bash
# Step 1: Check DNS operator
omc/oc get co dns

# Step 2: Check CoreDNS pods
omc/oc get pods -n openshift-dns
omc/oc logs -n openshift-dns <coredns-pod>

# Step 3: Test DNS resolution (live cluster only)
oc run -it --rm debug --image=registry.access.redhat.com/ubi8/ubi -- nslookup kubernetes.default.svc.cluster.local
oc run -it --rm debug --image=registry.access.redhat.com/ubi8/ubi -- nslookup <service>.<namespace>.svc.cluster.local

# Step 4: Check service endpoints
omc/oc get endpoints <service> -n <namespace>

# Step 5: Check NetworkPolicies
omc/oc get networkpolicy -n <namespace>
```

---

### Connection Refused / Timeout

**Signature Patterns**:
```
dial tcp <ip>:<port>: connect: connection refused
dial tcp <ip>:<port>: i/o timeout
context deadline exceeded
net/http: request canceled while waiting for connection
```

**Root Causes**:

1. **Service Not Ready** (50%)
   - Backend pods not running
   - Pods not passing readiness probe
   - Service selector not matching pods

2. **NetworkPolicy Blocking** (25%)
   - Ingress policy denying access
   - Egress policy blocking outbound
   - Namespaces not labeled correctly

3. **Firewall / Security Group** (15%)
   - Cloud firewall blocking
   - Host firewall on nodes
   - Security group rules

4. **Service Misconfiguration** (10%)
   - Wrong port in service
   - Service type incorrect
   - Target port mismatch

**Troubleshooting Steps**:

```bash
# Step 1: Check if service exists
omc/oc get svc <service> -n <namespace>

# Step 2: Check service endpoints
omc/oc get endpoints <service> -n <namespace>
# Empty endpoints = no ready pods matching selector

# Step 3: Verify pod selector
omc/oc get svc <service> -n <namespace> -o jsonpath='{.spec.selector}'
omc/oc get pods -n <namespace> -l <selector>

# Step 4: Check NetworkPolicies
omc/oc get networkpolicy -n <namespace>
omc/oc describe networkpolicy <policy> -n <namespace>

# Step 5: Check target pod status
omc/oc get pods -n <namespace>
omc/oc describe pod <pod> -n <namespace>
```

---

## Storage Failures

### PVC Stuck in Pending

**Signature Patterns**:
```
PersistentVolumeClaim is not bound: Pending
waiting for a volume to be created
no persistent volumes available
StorageClass "<name>" not found
```

**Root Causes**:

1. **StorageClass Missing** (35%)
   - StorageClass doesn't exist
   - StorageClass name typo in PVC

2. **CSI Driver Not Available** (30%)
   - CSI controller not running
   - CSI driver pods crashed
   - Incompatible CSI version

3. **Cloud Quota Exceeded** (20%)
   - Volume limit reached
   - Storage quota exhausted
   - EBS volume limit (AWS)

4. **No Matching PV** (15%)
   - No PV matches access mode
   - No PV matches capacity
   - All PVs already bound

**Troubleshooting Steps**:

```bash
# Step 1: Check PVC status
omc/oc describe pvc <pvc-name> -n <namespace>

# Step 2: Check if StorageClass exists
omc/oc get storageclass
omc/oc get pvc <pvc-name> -n <namespace> -o jsonpath='{.spec.storageClassName}'

# Step 3: Check CSI driver pods
omc/oc get pods -n openshift-cluster-csi-drivers

# Step 4: Check PVC events
omc/oc get events -n <namespace> | grep <pvc-name>

# Step 5: Check available PVs (if static provisioning)
omc/oc get pv
```

**Resolution by Cause**:

| Root Cause | Immediate Fix | Long-term Solution |
|------------|---------------|---------------------|
| Missing StorageClass | Create StorageClass or fix PVC | Document required StorageClasses |
| CSI driver down | Restart CSI pods, check operator | Monitor CSI driver health |
| Quota exceeded | Request quota increase | Implement capacity planning |
| No matching PV | Create PV or relax requirements | Use dynamic provisioning |

---

## Authentication/Authorization Failures

### Forbidden Errors

**Signature Patterns**:
```
Error from server (Forbidden): pods is forbidden: User "system:serviceaccount:X:Y" cannot list resource "pods"
forbidden: User "X" cannot get resource "Y" in API group "Z"
Unauthorized
```

**Root Causes**:

1. **Missing RBAC Permissions** (70%)
   - No Role/ClusterRole granting permission
   - No RoleBinding/ClusterRoleBinding
   - ServiceAccount not bound to role

2. **Expired Token** (15%)
   - ServiceAccount token expired
   - User authentication token invalid

3. **SCC Violation** (10%)
   - Pod requires privileged, only has restricted
   - Cannot run as root
   - Cannot access host network/ports

4. **API Server Issues** (5%)
   - API server denying all requests
   - Authorization webhook failure

**Troubleshooting Steps**:

```bash
# Step 1: Identify the user/service account
# (from error message)

# Step 2: Check RoleBindings
omc/oc get rolebinding -n <namespace>
omc/oc describe rolebinding <binding> -n <namespace>

# Step 3: Check ClusterRoleBindings
omc/oc get clusterrolebinding | grep <serviceaccount-name>

# Step 4: Check what permissions are granted
oc auth can-i --list --as=system:serviceaccount:<namespace>:<sa-name>  # Live only

# Step 5: For SCC issues, check pod security context
omc/oc get pod <pod> -n <namespace> -o yaml | grep -A 10 securityContext
omc/oc get scc  # List available SCCs
```

**Resolution**:

```yaml
# Create RoleBinding example
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: <binding-name>
  namespace: <namespace>
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole  # or Role
  name: <role-name>
subjects:
- kind: ServiceAccount
  name: <sa-name>
  namespace: <namespace>
```

---

## Test-Specific Failure Patterns

### Test Timeout

**Signature**:
```
FAIL: Test timed out after 10m0s
context deadline exceeded
timeout waiting for condition
```

**Categories**:

1. **Legitimate Timeout** (infrastructure slow)
   - Cloud API slow to provision
   - Volume provisioning takes longer than expected
   - Slow image pull

2. **Product Bug** (component genuinely slow)
   - Operator takes too long to reconcile
   - Pod startup extremely slow
   - API server performance issue

3. **Test Automation Issue** (timeout too short)
   - Hardcoded 1-minute wait insufficient
   - No retry logic
   - Timeout not adjusted for scale

**Diagnosis**:
- Check if resource eventually became ready (check events timeline)
- Compare timeout to similar tests
- Check if other tests on same cluster also timeout

---

## Summary: Quick Reference

### Top 10 Most Common Failures

1. **ImagePullBackOff** → Check registry auth, image exists, network
2. **CrashLoopBackOff** → Check --previous logs, OOMKilled, dependencies
3. **Pending (FailedScheduling)** → Check node capacity, taints, PVC
4. **ClusterOperator Degraded** → Check operator pods, logs, dependencies
5. **DNS failures** → Check CoreDNS, NetworkPolicy, service endpoints
6. **Connection refused** → Check service endpoints, NetworkPolicy
7. **PVC Pending** → Check StorageClass, CSI driver, quota
8. **Forbidden** → Check RBAC, SCC
9. **Timeout** → Check events, resource readiness, infrastructure
10. **Route 503** → Check IngressController, backend pods, router logs