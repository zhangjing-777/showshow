"""ShowShow CLI 主入口"""
import typer
from showshow.cli.diagnose import diagnose_app
from showshow.cli.path import path_app
from showshow.cli.inspect import inspect_app

app = typer.Typer(
    name="showshow",
    help="🕵️ ShowShow — GPU Fabric Network Diagnostics\n\n训练慢了？中断了？ShowShow一下，端网一起查，根因直接给你秀出来。",
    add_completion=False,
)

app.add_typer(diagnose_app, name="diagnose")
app.add_typer(path_app, name="path")
app.add_typer(inspect_app, name="inspect")


if __name__ == "__main__":
    app()
