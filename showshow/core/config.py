"""ShowShow 配置管理"""
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".showshow" / "config.yaml"


@dataclass
class ONCConfig:
    host: str = "127.0.0.1"
    port: int = 18080
    timeout: int = 30

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass
class SSHNodeConfig:
    user: str = "root"
    password: str = ""
    port: int = 22
    use_jump: bool = True   # 是否走跳板机，交换机设False直连


@dataclass
class JumpHostConfig:
    host: str = ""
    port: int = 2222
    user: str = ""
    password: str = ""


@dataclass
class SSHConfig:
    default_user: str = "root"
    default_password: str = ""
    default_port: int = 22
    jump_host: Optional[JumpHostConfig] = None
    nodes: Dict[str, SSHNodeConfig] = field(default_factory=dict)

    def get_node_config(self, ip: str) -> SSHNodeConfig:
        if ip in self.nodes:
            return self.nodes[ip]
        return SSHNodeConfig(
            user=self.default_user,
            password=self.default_password,
            port=self.default_port,
            use_jump=True,
        )


@dataclass
class NetworkConfig:
    roce_priority: int = 3
    config_cache_ttl: int = 300
    topology_mode: str = "ssh"
    leaf_ips: List[str] = field(default_factory=list)
    spine_ips: List[str] = field(default_factory=list)
    servers: Dict[str, str] = field(default_factory=dict)  # {ip: hostname}
    zone_id: int = 1


@dataclass
class ShowShowConfig:
    onc: ONCConfig = field(default_factory=ONCConfig)
    ssh: SSHConfig = field(default_factory=SSHConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)


def load_config(path: Optional[Path] = None) -> ShowShowConfig:
    config_path = path or DEFAULT_CONFIG_PATH

    if not config_path.exists():
        return ShowShowConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cfg = ShowShowConfig()

    if "onc" in raw:
        o = raw["onc"]
        cfg.onc = ONCConfig(
            host=o.get("host", cfg.onc.host),
            port=o.get("port", cfg.onc.port),
            timeout=o.get("timeout", cfg.onc.timeout),
        )

    if "ssh" in raw:
        s = raw["ssh"]
        jump_host = None
        if "jump_host" in s and s["jump_host"]:
            j = s["jump_host"]
            jump_host = JumpHostConfig(
                host=j.get("host", ""),
                port=j.get("port", 2222),
                user=j.get("user", ""),
                password=j.get("password", ""),
            )
        nodes = {}
        for ip, nc in (s.get("nodes") or {}).items():
            if not nc or not isinstance(nc, dict):
                continue
            nodes[str(ip)] = SSHNodeConfig(
                user=nc.get("user", s.get("default_user", "root")),
                password=nc.get("password", s.get("default_password", "")),
                port=nc.get("port", s.get("default_port", 22)),
                use_jump=nc.get("use_jump", True),
            )
        cfg.ssh = SSHConfig(
            default_user=s.get("default_user", "root"),
            default_password=s.get("default_password", ""),
            default_port=s.get("default_port", 22),
            jump_host=jump_host,
            nodes=nodes,
        )

    if "network" in raw:
        n = raw["network"]
        cfg.network = NetworkConfig(
            roce_priority=n.get("roce_priority", 3),
            config_cache_ttl=n.get("config_cache_ttl", 300),
            topology_mode=n.get("topology_mode", "ssh"),
            leaf_ips=n.get("leaf_ips") or [],
            spine_ips=n.get("spine_ips") or [],
            servers=n.get("servers") or {},
        )

    return cfg


_config: Optional[ShowShowConfig] = None


def get_config() -> ShowShowConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config
