#!/usr/bin/env python3
import os
import sys
import logging
from dataclasses import dataclass
from typing import List, Dict, Optional
from pathlib import Path

import click
from dotenv import load_dotenv
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich import box
from rich.progress import Progress, BarColumn, TextColumn

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
console = Console()


@dataclass
class NodeMetrics:
    name: str
    cpu_usage: int
    cpu_capacity: int
    memory_usage: int
    memory_capacity: int
    pod_count: int
    pod_capacity: int
    status: str
    labels: Dict[str, str]
    conditions: List[Dict]
    taints: List[Dict]


def load_config_from_env() -> Dict[str, str]:
    env_path = Path('.env')
    if env_path.exists():
        load_dotenv(env_path)
    return {
        'k8s_context': os.getenv('K8S_CONTEXT', ''),
    }


def get_node_metrics(core_v1: client.CoreV1Api, metrics_api) -> List[NodeMetrics]:
    nodes = core_v1.list_node()
    try:
        metrics = metrics_api.list_node_metrics()
        metrics_map = {m.metadata.name: m for m in metrics.items}
    except Exception as e:
        logger.warning(f"Metrics API unavailable: {e}")
        metrics_map = {}

    node_metrics = []
    for node in nodes.items:
        name = node.metadata.name

        cpu_capacity = int(node.status.capacity.get('cpu', '0'))
        memory_capacity = parse_memory(node.status.capacity.get('memory', '0'))
        pod_capacity = int(node.status.allocatable.get('pods', '0'))

        if name in metrics_map:
            m = metrics_map[name]
            cpu_usage = parse_cpu(m.usage.get('cpu', '0'))
            memory_usage = parse_memory(m.usage.get('memory', '0'))
        else:
            cpu_usage = 0
            memory_usage = 0

        pods = core_v1.list_pod_for_all_namespaces(field_selector=f'spec.nodeName={name}')
        pod_count = len(pods.items)

        status = "Ready" if any(c.type == "Ready" and c.status == "True" for c in node.status.conditions) else "NotReady"

        labels = node.metadata.labels or {}
        conditions = [{'type': c.type, 'status': c.status, 'reason': c.reason or ''} for c in node.status.conditions]
        taints = [{'key': t.key, 'effect': t.effect, 'value': t.value or ''} for t in (node.spec.taints or [])]

        node_metrics.append(NodeMetrics(
            name=name,
            cpu_usage=cpu_usage,
            cpu_capacity=cpu_capacity * 1000,
            memory_usage=memory_usage,
            memory_capacity=memory_capacity,
            pod_count=pod_count,
            pod_capacity=pod_capacity,
            status=status,
            labels=labels,
            conditions=conditions,
            taints=taints
        ))

    return node_metrics


def parse_cpu(cpu_str: str) -> int:
    if cpu_str.endswith('n'):
        return int(cpu_str[:-1]) // 1_000_000
    elif cpu_str.endswith('m'):
        return int(cpu_str[:-1])
    else:
        return int(cpu_str) * 1000


def parse_memory(mem_str: str) -> int:
    mem_str = str(mem_str).strip()
    if mem_str.endswith('Ki'):
        return int(mem_str[:-2]) * 1024
    elif mem_str.endswith('Mi'):
        return int(mem_str[:-2]) * 1024 * 1024
    elif mem_str.endswith('Gi'):
        return int(mem_str[:-2]) * 1024 * 1024 * 1024
    elif mem_str.endswith('K'):
        return int(mem_str[:-1]) * 1000
    elif mem_str.endswith('M'):
        return int(mem_str[:-1]) * 1000 * 1000
    elif mem_str.endswith('G'):
        return int(mem_str[:-1]) * 1000 * 1000 * 1000
    else:
        return int(mem_str)


def format_memory(bytes_val: int) -> str:
    gb = bytes_val / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.1f}Gi"
    mb = bytes_val / (1024 ** 2)
    return f"{mb:.0f}Mi"


def get_color_for_usage(percent: float) -> str:
    if percent >= 90:
        return "red"
    elif percent >= 75:
        return "yellow"
    elif percent >= 50:
        return "cyan"
    else:
        return "green"


def print_node_details(node: NodeMetrics):
    cpu_percent = (node.cpu_usage / node.cpu_capacity * 100) if node.cpu_capacity > 0 else 0
    mem_percent = (node.memory_usage / node.memory_capacity * 100) if node.memory_capacity > 0 else 0
    pod_percent = (node.pod_count / node.pod_capacity * 100) if node.pod_capacity > 0 else 0

    status_color = "green" if node.status == "Ready" else "red"

    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_column("Key", style="bold dim")
    table.add_column("Value")

    table.add_row("Status", f"[{status_color}]{node.status}[/{status_color}]")
    table.add_row("Pods", f"{node.pod_count}/{node.pod_capacity} [{get_color_for_usage(pod_percent)}]({pod_percent:.0f}%)[/{get_color_for_usage(pod_percent)}]")

    cpu_color = get_color_for_usage(cpu_percent)
    table.add_row("CPU", f"{node.cpu_usage}m/{node.cpu_capacity}m [{cpu_color}]({cpu_percent:.0f}%)[/{cpu_color}]")

    mem_color = get_color_for_usage(mem_percent)
    table.add_row("Memory", f"{format_memory(node.memory_usage)}/{format_memory(node.memory_capacity)} [{mem_color}]({mem_percent:.0f}%)[/{mem_color}]")

    if node.taints:
        for i, t in enumerate(node.taints):
            label = "Taints" if i == 0 else ""
            table.add_row(label, f"[red]{t['key']}={t['effect']}[/red]")

    autoscaler_labels = {k: v for k, v in node.labels.items() if 'autoscal' in k.lower() or 'scale' in k.lower()}
    if autoscaler_labels:
        for k, v in autoscaler_labels.items():
            table.add_row(f"  {k}", f"[cyan]{v}[/cyan]")

    panel = Panel(
        table,
        title=f"[bold cyan]{node.name}[/bold cyan]",
        border_style=status_color,
        box=box.ROUNDED
    )
    console.print(panel)


def print_summary(nodes: List[NodeMetrics]):
    total_nodes = len(nodes)
    ready_nodes = sum(1 for n in nodes if n.status == "Ready")
    total_cpu_usage = sum(n.cpu_usage for n in nodes)
    total_cpu_capacity = sum(n.cpu_capacity for n in nodes)
    total_mem_usage = sum(n.memory_usage for n in nodes)
    total_mem_capacity = sum(n.memory_capacity for n in nodes)
    total_pods = sum(n.pod_count for n in nodes)

    tainted_nodes = sum(1 for n in nodes if n.taints)

    cpu_percent = (total_cpu_usage / total_cpu_capacity * 100) if total_cpu_capacity > 0 else 0
    mem_percent = (total_mem_usage / total_mem_capacity * 100) if total_mem_capacity > 0 else 0

    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    table.add_row("Cluster", f"[cyan]{os.getenv('K8S_CONTEXT', 'current')}[/cyan]")
    table.add_row("Total Nodes", f"{total_nodes}")
    table.add_row("Ready Nodes", f"[green]{ready_nodes}[/green] / {total_nodes}")
    table.add_row("Tainted Nodes", f"[yellow]{tainted_nodes}[/yellow]" if tainted_nodes > 0 else "[dim]0[/dim]")
    table.add_row("", "")

    cpu_color = get_color_for_usage(cpu_percent)
    table.add_row("Cluster CPU", f"[{cpu_color}]{cpu_percent:.1f}%[/{cpu_color}] ({total_cpu_usage}m / {total_cpu_capacity}m)")

    mem_color = get_color_for_usage(mem_percent)
    table.add_row("Cluster Memory", f"[{mem_color}]{mem_percent:.1f}%[/{mem_color}] ({format_memory(total_mem_usage)} / {format_memory(total_mem_capacity)})")

    table.add_row("Total Pods", f"[blue]{total_pods}[/blue]")

    header = Panel(
        Text("OKE Node Inspector", style="bold cyan", justify="center"),
        box=box.DOUBLE,
        border_style="cyan"
    )
    console.print()
    console.print(header)
    console.print()
    console.print(table)
    console.print()


@click.command()
@click.option('--filter-tainted', is_flag=True, help='Show only tainted nodes')
@click.option('--filter-high-usage', is_flag=True, help='Show nodes with >75% CPU or memory')
@click.option('--sort-by', type=click.Choice(['cpu', 'memory', 'pods', 'name']), default='name', help='Sort nodes by metric')
@click.option('--verbose', is_flag=True, help='Show detailed node conditions')
def main(filter_tainted: bool, filter_high_usage: bool, sort_by: str, verbose: bool):
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        config_dict = load_config_from_env()

        if config_dict['k8s_context']:
            config.load_kube_config(context=config_dict['k8s_context'])
        else:
            config.load_kube_config()

        core_v1 = client.CoreV1Api()

        try:
            from kubernetes import client as k8s_client
            metrics_api = k8s_client.CustomObjectsApi()

            class MetricsAPI:
                def __init__(self, custom_api):
                    self.custom_api = custom_api

                def list_node_metrics(self):
                    result = self.custom_api.list_cluster_custom_object(
                        group="metrics.k8s.io",
                        version="v1beta1",
                        plural="nodes"
                    )

                    class MetricItem:
                        def __init__(self, data):
                            self.metadata = type('obj', (object,), {'name': data['metadata']['name']})
                            self.usage = data['usage']

                    class MetricsList:
                        def __init__(self, data):
                            self.items = [MetricItem(item) for item in data['items']]

                    return MetricsList(result)

            metrics_api = MetricsAPI(metrics_api)
        except Exception as e:
            logger.warning(f"Metrics API setup failed: {e}")
            metrics_api = None

        nodes = get_node_metrics(core_v1, metrics_api)

        if filter_tainted:
            nodes = [n for n in nodes if n.taints]

        if filter_high_usage:
            nodes = [n for n in nodes if
                     (n.cpu_usage / n.cpu_capacity * 100 > 75 if n.cpu_capacity > 0 else False) or
                     (n.memory_usage / n.memory_capacity * 100 > 75 if n.memory_capacity > 0 else False)]

        if sort_by == 'cpu':
            nodes.sort(key=lambda n: n.cpu_usage / n.cpu_capacity if n.cpu_capacity > 0 else 0, reverse=True)
        elif sort_by == 'memory':
            nodes.sort(key=lambda n: n.memory_usage / n.memory_capacity if n.memory_capacity > 0 else 0, reverse=True)
        elif sort_by == 'pods':
            nodes.sort(key=lambda n: n.pod_count / n.pod_capacity if n.pod_capacity > 0 else 0, reverse=True)
        else:
            nodes.sort(key=lambda n: n.name)

        print_summary(nodes)

        for node in nodes:
            print_node_details(node)

        console.print()

    except ApiException as e:
        console.print(f"[red]Kubernetes API error: {e.reason}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
