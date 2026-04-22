"""
showshow inspect 命令
巡检：预防性检查主机和网络配置
"""

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from typing import Optional, List

from showshow.inspectors.checklist import Inspector

inspect_app = typer.Typer(help="巡检：预防性检查主机和网络配置")
console = Console()


@inspect_app.callback(invoke_without_command=True)
def inspect(
    nodes: Optional[str] = typer.Option(
        None, "--nodes", "-n", help="指定节点IP，逗号分隔，不填则全量"
    ),
    scope: str = typer.Option(
        "all", "--scope", help="检查范围: host / network / all"
    ),
):
    """
    集群巡检

    示例：
      showshow inspect
      showshow inspect --nodes 10.159.161.1,10.159.161.2 --scope host
      showshow inspect --scope network
    """
    node_list: Optional[List[str]] = None
    if nodes:
        node_list = [n.strip() for n in nodes.split(",")]

    with console.status("[bold yellow]执行巡检..."):
        inspector = Inspector()
        results = inspector.run(node_list=node_list, scope=scope)

    # 汇总
    total = len(results)
    passed = sum(1 for r in results if r.status == "pass")
    warning = sum(1 for r in results if r.status == "warning")
    failed = sum(1 for r in results if r.status == "fail")

    summary_color = "green" if failed == 0 else "red"
    console.print(Panel(
        f"总计: {total}  [green]通过: {passed}[/green]  "
        f"[yellow]警告: {warning}[/yellow]  [red]失败: {failed}[/red]",
        title=f"[{summary_color}]巡检结果[/{summary_color}]",
    ))

    if failed > 0 or warning > 0:
        table = Table(show_header=True, header_style="bold")
        table.add_column("节点")
        table.add_column("检查项")
        table.add_column("状态")
        table.add_column("说明")
        table.add_column("建议")

        for r in results:
            if r.status in ("fail", "warning"):
                status_str = "[red]✗ 失败[/red]" if r.status == "fail" else "[yellow]⚠ 警告[/yellow]"
                table.add_row(
                    r.node_ip,
                    r.check_name,
                    status_str,
                    r.actual or "",
                    r.suggestion or "",
                )
        console.print(table)
