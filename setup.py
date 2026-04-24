from setuptools import setup, find_packages

setup(
    name="showshow",
    version="0.1.0",
    description="GPU Fabric Network Diagnostics - 训练慢了？ShowShow一下",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "typer[all]>=0.9.0",
        "requests>=2.31.0",
        "paramiko>=3.0.0",
        "pyyaml>=6.0",
        "pycryptodome>=3.18.0",
        "netmiko>=4.0.0",
        "rich>=13.0.0",
    ],
    entry_points={
        "console_scripts": [
            "showshow=showshow.cli.main:app",
        ],
    },
)
