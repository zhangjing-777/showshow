"""SSH 连接封装，交换机用netmiko，服务器用paramiko"""
import time
import paramiko
from typing import Optional, Dict, Tuple
from showshow.core.config import get_config

try:
    from netmiko import ConnectHandler
    HAS_NETMIKO = True
except ImportError:
    HAS_NETMIKO = False


class SSHClient:
    def __init__(self):
        self.cfg = get_config()
        self._cache: Dict[str, Tuple[str, float]] = {}
        self._jump_client: Optional[paramiko.SSHClient] = None

    def _get_jump_sock(self, ip: str, port: int):
        """通过跳板机建立channel，返回sock供paramiko/netmiko使用"""
        jump_cfg = self.cfg.ssh.jump_host
        node_cfg = self.cfg.ssh.get_node_config(ip)
        if not node_cfg.use_jump or not jump_cfg or not jump_cfg.host:
            return None

        if self._jump_client:
            try:
                self._jump_client.get_transport().send_ignore()
            except Exception:
                self._jump_client = None

        if not self._jump_client:
            j = paramiko.SSHClient()
            j.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            j.connect(
                hostname=jump_cfg.host,
                port=jump_cfg.port,
                username=jump_cfg.user,
                password=jump_cfg.password,
                timeout=10,
                allow_agent=False,
                look_for_keys=False,
            )
            self._jump_client = j

        channel = self._jump_client.get_transport().open_channel(
            "direct-tcpip", (ip, port), ("", 0)
        )
        return channel

    def exec(self, ip: str, command: str) -> str:
        """Linux服务器用paramiko exec_command"""
        node_cfg = self.cfg.ssh.get_node_config(ip)
        sock = self._get_jump_sock(ip, node_cfg.port)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=ip,
            port=node_cfg.port,
            username=node_cfg.user,
            password=node_cfg.password,
            sock=sock,
            timeout=10,
            allow_agent=False,
            look_for_keys=False,
        )
        try:
            _, stdout, _ = client.exec_command(command, timeout=30)
            return stdout.read().decode("utf-8", errors="replace")
        finally:
            client.close()

    def exec_switch(self, ip: str, command: str) -> str:
        """交换机用netmiko，专门处理网络设备回显"""
        if not HAS_NETMIKO:
            raise RuntimeError("请先安装netmiko: pip install netmiko")

        node_cfg = self.cfg.ssh.get_node_config(ip)
        sock = self._get_jump_sock(ip, node_cfg.port)

        device = {
            "device_type": "ruijie_os",
            "host": ip,
            "port": node_cfg.port,
            "username": node_cfg.user,
            "password": node_cfg.password,
            "timeout": 30,
            "session_timeout": 60,
        }
        if sock:
            device["sock"] = sock

        with ConnectHandler(**device) as conn:
            output = conn.send_command(command)
        return output

    def get_running_config(self, ip: str, force_refresh: bool = False) -> str:
        ttl = self.cfg.network.config_cache_ttl
        now = time.time()
        if not force_refresh and ip in self._cache:
            cached_output, expire_time = self._cache[ip]
            if now < expire_time:
                return cached_output
        output = self.exec_switch(ip, "show run")
        self._cache[ip] = (output, now + ttl)
        return output

    def get_pcie_topology(self, ip: str) -> str:
        return self.exec(ip, "nvidia-smi topo -m")

    def get_pcie_bandwidth(self, ip: str) -> str:
        return self.exec(
            ip,
            "nvidia-smi --query-gpu=index,pcie.link.gen.current,"
            "pcie.link.width.current,pcie.link.gen.max,"
            "pcie.link.width.max --format=csv,noheader",
        )

    def get_nic_list(self, ip: str) -> str:
        return self.exec(ip, "ip link show | grep -E '^[0-9]+:'")
