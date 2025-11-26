# OKE Node Inspector

Shows CPU/Memory usage, pod count, and autoscaler status for OKE nodes.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Config

Create `.env`:
```bash
K8S_CONTEXT=your-context-name
```

## Usage

```bash
# Show all nodes
python oci_oke_node_inspector.py

# Only tainted nodes
python oci_oke_node_inspector.py --filter-tainted

# Only high usage nodes (>75%)
python oci_oke_node_inspector.py --filter-high-usage

# Sort by CPU usage
python oci_oke_node_inspector.py --sort-by cpu

# Sort by memory usage
python oci_oke_node_inspector.py --sort-by memory
```

## Output

Shows cluster summary and per-node boxes:

```
╔══════════════════════════════════════╗
║        OKE Node Inspector            ║
╚══════════════════════════════════════╝

Cluster           context-cyocvdj7kvq
Total Nodes       30
Ready Nodes       30 / 30
Tainted Nodes     2

Cluster CPU       45.2% (45000m / 100000m)
Cluster Memory    62.1% (32.5Gi / 52.3Gi)
Total Pods        245

╭─────────────────────────────────────╮
│ 10.1.193.50                         │
├─────────────────────────────────────┤
│ Status     Ready                    │
│ Pods       12/110 (10%)             │
│ CPU        450m/2000m (22%)         │
│ Memory     1.2Gi/7.5Gi (16%)        │
│ Taints     node.kubernetes.io/unschedulable=NoSchedule
╰─────────────────────────────────────╯
```

## Metrics

Per node:
- Status (Ready/NotReady)
- Pod count and capacity
- CPU usage (millicores)
- Memory usage (GiB/MiB)
- Taints (if any)
- Autoscaler labels

Cluster:
- Total/ready nodes
- Tainted node count
- Cluster-wide CPU/memory usage
- Total pod count

## Filters

- `--filter-tainted` - Show only nodes with taints
- `--filter-high-usage` - Show nodes >75% CPU or memory
- `--sort-by cpu|memory|pods|name` - Sort order

## Colors

- 🟢 Green: <50% usage
- 🔵 Cyan: 50-75% usage
- 🟡 Yellow: 75-90% usage
- 🔴 Red: >90% usage

## Fix Metrics RBAC

If CPU/Memory shows 0%, apply RBAC:

```bash
kubectl apply -f rbac.yaml
```

Or if you're using a service account:

```bash
kubectl create clusterrolebinding node-metrics-reader \
  --clusterrole=view \
  --serviceaccount=default:default
```

## Requirements

- Python 3.9+
- kubectl access
- Metrics Server installed (for CPU/memory data)
