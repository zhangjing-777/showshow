"""showshow path 命令"""
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from typing import Optional

from showshow.analyzers.ailb import AILBAnalyzer

path_app = typer.Typer(help="路径查询：查看两节点间的AILB转发路径")
console = Console()


@path_app.callback(invoke_without_command=True)
def path(
    src: str = typer.Option(..., "--src", "-s", help="源节点IP"),
    dst: str = typer.Option(..., "--dst", "-d", help="目的节点IP"),
    mode: str = typer.Option(None, "--mode", "-m", help="拓扑模式: ssh或onc"),
    zone_id: int = typer.Option(None, "--zone", help="ONC区域ID"),
    no_cache: bool = typer.Option(False, "--no-cache", help="强制刷新配置缓存"),
):
    """
    查询AILB路径并验证

    示例：
      showshow path --src 198.18.24.9 --dst 198.18.139.9
    """
    with console.status("[bold yellow]还原AILB路径..."):
        ailb = AILBAnalyzer()
        result = ailb.resolve_path(src, dst, mode=mode, zone_id=zone_id, force_refresh=no_cache)

    if not result.is_valid():
        console.print(f"[red]✗ 路径还原失败: {result.error}[/red]")
        raise typer.Exit(1)

    if result.is_ailb:
        # ✅ AILB正常，一张表
        console.print(Panel(
            f"[bold]{src}[/bold] → [bold]{dst}[/bold]\n\n" + result.summary(),
            title="[green]✅ AILB路径正常[/green]",
            border_style="green",
        ))
        _print_hop_table(result.hops, title="路径详情")
    else:
        # ⚠️ AILB异常，两张表
        console.print(Panel(
            f"[bold]{src}[/bold] → [bold]{dst}[/bold]\n\n"
            f"[yellow]⚠️ AILB主路径异常，已fallback到ECMP[/yellow]",
            title="[yellow]⚠️ AILB路径异常[/yellow]",
            border_style="yellow",
        ))

        # 表1：AILB理论路径（标注DOWN）
        console.print("\n[bold yellow]AILB理论路径（配置期望路径）：[/bold yellow]")
        _print_hop_table(result.hops, title="AILB理论路径", show_ailb_status=True)

        # 表2：实际ECMP路径（从路由表来）
        if result.actual_hops:
            console.print("\n[bold cyan]实际转发路径（路由表，ECMP fallback）：[/bold cyan]")
            _print_hop_table(result.actual_hops, title="实际路径")

    # AILB计算详情
    console.print()
    console.print("[dim]AILB计算详情：[/dim]")
    if result.hops:
        console.print(f"  src_tag            = {result.hops[0].ip_tag}")
        console.print(f"  dst_tag            = {result.hops[-1].ip_tag}")
    console.print(f"  LEAF_src member-id = {result.ailb_member_id_src}")
    console.print(f"  LEAF_dst member-id = {result.ailb_member_id_dst}")


def _print_hop_table(hops, title="", show_ailb_status=False):
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("跳数", style="dim", width=4)
    table.add_column("设备")
    table.add_column("IP", style="dim")
    table.add_column("角色")
    table.add_column("入端口", style="cyan")
    table.add_column("出端口", style="cyan")
    table.add_column("ip_tag", justify="right")
    table.add_column("AILB状态" if show_ailb_status else "状态")

    for i, hop in enumerate(hops):
        role_color = {"server": "cyan", "leaf": "yellow", "spine": "magenta"}.get(
            hop.device_role, "white"
        )
        if show_ailb_status:
            status = "[green]✓ 正常[/green]" if hop.is_up else "[red]✗ DOWN（主路径异常）[/red]"
        else:
            status = "[green]✓ UP[/green]" if hop.is_up else "[red]✗ DOWN[/red]"

        table.add_row(
            str(i + 1),
            f"[{role_color}]{hop.device_name}[/{role_color}]",
            hop.device_ip,
            hop.device_role,
            hop.in_port or "-",
            hop.out_port or "-",
            str(hop.ip_tag) if hop.ip_tag else "-",
            status,
        )
    console.print(table)
