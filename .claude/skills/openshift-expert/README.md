# OpenShift Expert Skill

An intelligent AI skill that provides deep OpenShift platform expertise for test failure analysis, cluster troubleshooting, and root cause determination.

## Overview

This skill makes Claude Code an **OpenShift domain expert** that can:

- 🔍 **Recognize failure patterns** - Instantly identify common OpenShift/Kubernetes issues
- 🎯 **Diagnose root causes** - Distinguish between product bugs, test automation issues, and infrastructure problems
- 🛠️ **Provide targeted troubleshooting** - Suggest specific commands and steps based on failure type
- 📊 **Analyze cluster state** - Interpret must-gather data and live cluster diagnostics
- 🧠 **Apply OpenShift knowledge** - Deep understanding of operators, networking, storage, and architecture

## Automatic Activation

This skill is **automatically invoked** by Claude when:

- Analyzing OpenShift CI test failures
- Debugging cluster issues
- Investigating operator degradation
- Troubleshooting networking or storage problems
- Answering OpenShift architecture questions

You don't need to explicitly call it - Claude will use this skill when the context matches.

## Contents

### Main Skill Definition
- **SKILL.md** - Core skill with OpenShift expertise, troubleshooting methodology, and analysis framework

### Knowledge Base
- **knowledge/failure-patterns.md** - Comprehensive catalog of failure signatures with root causes and resolutions
- **knowledge/operators.md** - Per-operator troubleshooting guides for all core cluster operators

### Helper Scripts
- **scripts/categorize-failure.py** - Pattern-matching script for automated failure categorization

## Usage with Slash Commands

This skill enhances all OpenShift-related slash commands:

```bash
# Analyze Prow job failures - skill provides OpenShift expertise
/ci:analyze-prow-failures https://deck.../job/123

# Analyze Jenkins job failures - skill helps with cluster analysis
/ci:analyze-jenkins-failures https://jenkins.../job/stage-testing/456

# Analyze build test results - skill interprets test failures
/ci:analyze-build-test-results 4.19.0-0.nightly-2025-01-15-123456
```

## Key Features

### 1. Failure Pattern Recognition

Instantly recognizes common patterns:
- **ImagePullBackOff** - Registry authentication, missing images, network issues
- **CrashLoopBackOff** - Application crashes, OOMKilled, missing dependencies
- **ClusterOperator Degraded** - Operator-specific issues with targeted troubleshooting
- **DNS Resolution Failures** - CoreDNS, NetworkPolicy, service endpoint issues
- **Storage Failures** - PVC pending, CSI driver issues, volume mount failures
- **RBAC Errors** - Permission issues, SCC violations

### 2. Cluster Access Awareness

Automatically adapts commands based on cluster access method:

**Must-gather Analysis** (Post-mortem):
```bash
omc use /tmp/must-gather-{job_run_id}/
omc get co
omc logs -n openshift-dns <pod>
```

**Live Cluster Access** (Real-time):
```bash
oc get co
oc logs -n openshift-dns <pod>
oc top nodes  # Real-time metrics
```

### 3. Root Cause Analysis Framework

Provides structured analysis with:
- **Primary hypothesis** with confidence level (High/Medium/Low)
- **Evidence** from logs, events, and cluster state
- **Category** (Product Bug / Test Automation / Infrastructure / Configuration)
- **Affected components** and dependency chains
- **Actionable recommendations** (Immediate / Investigation / Long-term)

### 4. Operator Expertise

Deep knowledge of all core operators:
- etcd, kube-apiserver, network, dns
- **machine-config-operator** - Node configuration, OS updates, MachineConfig reconciliation
- **machine-api** - Infrastructure management, Machine/MachineSet, cloud provisioning
- ingress, authentication, console
- storage, image-registry, monitoring, OLM

## Example: How the Skill Helps

**Without the skill:**
```
User: Why is this test failing?
Claude: The test shows "ClusterOperator authentication is degraded".
        You should check the authentication operator.
```

**With the OpenShift expert skill:**
```
User: Why is this test failing?
Claude: [Invokes openshift-expert skill automatically]

This is an authentication operator degradation. Based on the error pattern
"OAuthServerDeploymentDegraded", I can provide targeted analysis:

Root Cause Analysis:
- Primary Hypothesis (Confidence: 90%): OAuth server deployment unavailable
- Category: Product Bug
- Evidence:
  1. ClusterOperator authentication shows Available=False
  2. OAuth pods in openshift-authentication namespace are CrashLooping
  3. Logs show "failed to mount secret oauth-serving-cert"

Affected Components:
- authentication operator: Degraded
- OAuth server deployment: Not available
- oauth-serving-cert secret: Missing or inaccessible

Dependency Chain:
authentication ← ingress ← dns (all dependencies healthy)

Recommended Actions:
1. Immediate: Check if oauth-serving-cert secret exists:
   omc/oc get secret -n openshift-authentication | grep oauth-serving-cert

2. Investigation: Check certificate rotation:
   omc/oc logs -n openshift-authentication oauth-openshift-* --previous

3. Long-term: File OCPBUGS for certificate secret management issue

This is a product bug requiring OCPBUGS ticket.
```

## Helper Script Usage

### Automated Failure Categorization

```bash
# Prepare failure data
cat > failures.json << EOF
[
  {
    "test_name": "test-pod-creation",
    "error_message": "Failed to pull image: unauthorized",
    "stack_trace": "..."
  }
]
EOF

# Categorize
python3 .claude/skills/openshift-expert/scripts/categorize-failure.py < failures.json

# Output includes:
# - Pattern matched
# - Category (infrastructure/operator/networking/etc.)
# - Confidence level
# - Likely cause (product_bug/test_automation/infrastructure)
```

## Integration with Existing Tools

This skill works seamlessly with:

- **ci_job_failure_fetcher.py** - Provides structured failure data
- **omc** - Must-gather analysis commands
- **oc** - Live cluster debugging
- **Jira MCP** - Known issue correlation
- **Test code analysis** - Distinguishes test bugs from product bugs

## Skill Knowledge Updates

To update the skill's knowledge:

1. **Edit SKILL.md** - Add new troubleshooting patterns or methodologies
2. **Update failure-patterns.md** - Add newly discovered failure signatures
3. **Update operators.md** - Add new operators or update troubleshooting steps
4. **Enhance scripts** - Add new pattern matching rules

Changes take effect on next Claude Code restart.

## Verification

Check if the skill is loaded:

```bash
# In Claude Code chat
"What skills are available?"

# Should include: openshift-expert
```

Or check directly:
```bash
ls -la .claude/skills/openshift-expert/
```

## Troubleshooting

**Skill not being invoked?**
- Check that SKILL.md has valid YAML frontmatter
- Ensure description clearly indicates when to use the skill
- Try more explicit prompts: "Use OpenShift expertise to analyze this failure"

**Need more specific knowledge?**
- Add patterns to `knowledge/failure-patterns.md`
- Add operator details to `knowledge/operators.md`
- Reference these files in your prompts

## Contributing

To improve this skill:

1. Add new failure patterns as you encounter them
2. Document operator-specific troubleshooting workflows
3. Update confidence levels based on real-world accuracy
4. Add examples of successful root cause analyses

---

**Powered by Claude Code Skills**

This skill makes Claude Code your OpenShift expert assistant for all cluster troubleshooting and test failure analysis tasks.