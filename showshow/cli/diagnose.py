"""
showshow diagnose 命令
输入：src_node, dst_node, 时间点
输出：路径 + 每跳指标 + 根因定位
"""

import time
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint
from typing import Optional

from showshow.analyzers.ailb import AILBAnalyzer
from showshow.analyzers.metrics import MetricsAnalyzer
from showshow.analyzers.pcie import PCIeAnalyzer

diagnose_app = typer.Typer(help="故障诊断：输入两个节点IP，输出根因定位")
console = Console()


@diagnose_app.callback(invoke_without_command=True)
def diagnose(
    src: str = typer.Option(..., "--src", "-s", help="源节点IP（GPU服务器）"),
    dst: str = typer.Option(..., "--dst", "-d", help="目的节点IP（GPU服务器）"),
    time_point: Optional[str] = typer.Option(
        None, "--time", "-t", help="故障时间点，格式: '2024-01-10 14:00'，不填则查最近1小时"
    ),
    zone_id: int = typer.Option(1, "--zone", help="ONC区域ID"),
    with_pcie: bool = typer.Option(False, "--pcie", help="是否包含PCIe拓扑分析"),
    no_cache: bool = typer.Option(False, "--no-cache", help="强制刷新设备配置缓存"),
):
    """
    端到端故障诊断

    示例：
      showshow diagnose --src 10.159.161.1 --dst 10.159.161.8
      showshow diagnose --src 10.159.161.1 --dst 10.159.161.8 --time "2024-01-10 14:00"
      showshow diagnose --src 10.159.161.1 --dst 10.159.161.8 --pcie
    """
    # 计算时间范围
    end_ts, start_ts = _parse_time(time_point)

    console.print(Panel(
        f"[bold cyan]ShowShow 故障诊断[/bold cyan]\n"
        f"  源节点: [green]{src}[/green]\n"
        f"  目的节点: [green]{dst}[/green]\n"
        f"  时间范围: {_fmt_ts(start_ts)} ~ {_fmt_ts(end_ts)}",
        title="🕵️ ShowShow",
    ))

    # Step1: 路径还原
    with console.status("[bold yellow][1/4] 还原AILB路径..."):
        ailb = AILBAnalyzer()
        path = ailb.resolve_path(src, dst, zone_id=zone_id, force_refresh=no_cache)

    if not path.is_valid():
        console.print(f"[red]✗ 路径还原失败: {path.error}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] 路径还原完成")
    _print_path(path)

    # Step2: PCIe拓扑（可选）
    if with_pcie:
        with console.status("[bold yellow][2/4] 获取PCIe拓扑..."):
            pcie_analyzer = PCIeAnalyzer()
            pcie_src = pcie_analyzer.get_topology(src)
            pcie_dst = pcie_analyzer.get_topology(dst)
        console.print(f"[green]✓[/green] PCIe拓扑获取完成")
        _print_pcie(src, pcie_src)
        _print_pcie(dst, pcie_dst)

    # Step3: 拉取路径上各节点指标
    with console.status("[bold yellow][3/4] 拉取路径指标..."):
        metrics_analyzer = MetricsAnalyzer()
        node_metrics = []
        for hop in path.hops:
            if hop.device_role in ("leaf", "spine"):
                port = hop.out_port or hop.in_port
                m = metrics_analyzer.analyze_switch_port(
                    hop.device_ip, hop.device_name, hop.device_role,
                    port, start_ts, end_ts,
                )
                node_metrics.append(m)

    console.print(f"[green]✓[/green] 指标拉取完成")

    # Step4: 异常判定和根因输出
    with console.status("[bold yellow][4/4] 分析根因..."):
        anomaly_nodes = [m for m in node_metrics if m.has_anomaly()]

    _print_metrics_table(node_metrics)

    console.print()
    if anomaly_nodes:
        console.print(Panel(
            "\n".join([
                f"[red]⚠️  {m.device_name}({m.port})[/red]\n"
                + "\n".join([f"    • {a}" for a in m.anomalies])
                for m in anomaly_nodes
            ]),
            title="[red bold]El Culpable 根因定位[/red bold]",
            border_style="red",
        ))
    else:
        console.print(Panel(
            "[green]路径上各节点指标正常，网络侧未发现异常[/green]\n"
            "建议检查：主机侧配置（运行 showshow inspect）或应用层问题",
            title="[green]✓ 网络正常[/green]",
            border_style="green",
        ))

    console.print(f"\n[dim]报告生成完成[/dim]")


def _parse_time(time_point: Optional[str]):
    """解析时间参数，返回 (end_ts_ms, start_ts_ms)"""
    if time_point:
        import datetime
        dt = datetime.datetime.strptime(time_point, "%Y-%m-%d %H:%M")
        end_ts = int(dt.timestamp() * 1000) + 1800_000   # 时间点+30分钟
        start_ts = int(dt.timestamp() * 1000) - 1800_000  # 时间点-30分钟
    else:
        end_ts = int(time.time() * 1000)
        start_ts = end_ts - 3600_000  # 最近1小时
    return end_ts, start_ts


def _fmt_ts(ts_ms: int) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def _print_path(path):
    console.print()
    console.print("[bold]📍 完整路径：[/bold]")
    for i, hop in enumerate(path.hops):
        role_color = {"server": "cyan", "leaf": "yellow", "spine": "magenta"}.get(
            hop.device_role, "white"
        )
        port_info = ""
        if hop.in_port and hop.out_port:
            port_info = f" [dim]({hop.in_port} → {hop.out_port})[/dim]"
        elif hop.in_port:
            port_info = f" [dim](← {hop.in_port})[/dim]"
        elif hop.out_port:
            port_info = f" [dim](→ {hop.out_port})[/dim]"

        ailb_info = ""
        if hop.device_role == "leaf" and hop.member_id:
            ailb_info = f" [dim cyan][AILB member-id={hop.member_id}][/dim cyan]"

        arrow = "  ↓\n" if i < len(path.hops) - 1 else ""
        console.print(
            f"  [{role_color}]{hop.device_name}[/{role_color}]{port_info}{ailb_info}\n{arrow}",
            end="",
        )
    console.print()


def _print_pcie(node_ip: str, pcie):
    console.print(f"\n[bold]🔌 PCIe拓扑 [{node_ip}]：[/bold]")
    if pcie.error:
        console.print(f"  [red]{pcie.error}[/red]")
        return
    console.print(pcie.summary())
    if pcie.gpu_nic_relations:
        console.print("\n  [dim]GPU-NIC连接关系：[/dim]")
        for nic, rel in pcie.gpu_nic_relations.items():
            console.print(f"  {nic}: {rel}")


def _print_metrics_table(node_metrics):
    if not node_metrics:
        return
    console.print()
    table = Table(title="📊 路径节点指标", show_header=True, header_style="bold cyan")
    table.add_column("节点", style="white")
    table.add_column("端口", style="dim")
    table.add_column("PFC发送率", justify="right")
    table.add_column("PFC接收率", justify="right")
    table.add_column("ECN速率", justify="right")
    table.add_column("TX丢包", justify="right")
    table.add_column("Headroom%", justify="right")
    table.add_column("NAK", justify="right")
    table.add_column("状态")

    for m in node_metrics:
        status = "[red]⚠️ 异常[/red]" if m.has_anomaly() else "[green]✓[/green]"
        headroom = f"{m.headroom_used:.1f}%" if m.headroom_used else "-"
        table.add_row(
            m.device_name,
            m.port or "-",
            f"{m.pfc_send_rate:.0f}",
            f"{m.pfc_recv_rate:.0f}",
            f"{m.ecn_rate:.0f}",
            f"{m.tx_drop:.0f}",
            headroom,
            f"{m.nak_tx:.0f}/{m.nak_rx:.0f}",
            status,
        )

    console.print(table)
