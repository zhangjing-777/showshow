"""
AILB 路径还原

数据来源：
  ONC API → server-leaf连接关系、设备IP/hostname
  SSH     → BGP member_id + ip_tag + SPINE端口映射(LLDP)
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from showshow.adapters.ssh import SSHClient
from showshow.adapters.onc import ONCClient
from showshow.core.config import get_config


@dataclass
class AILBConfig:
    device_ip: str
    hostname: str
    bgp_as: str = ""
    member_map: Dict[int, str] = field(default_factory=dict)
    neighbor_to_member: Dict[str, int] = field(default_factory=dict)
    port_tag_map: Dict[str, int] = field(default_factory=dict)
    port_to_spine: Dict[str, str] = field(default_factory=dict)
    port_status: Dict[str, bool] = field(default_factory=dict)
    neighbor_to_port: Dict[str, str] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.member_map)

    def calc_member_id(self, dst_tag: int) -> int:
        if self.count == 0:
            return 0
        mid = dst_tag % self.count
        return mid if mid != 0 else self.count


@dataclass
class HopInfo:
    device_name: str
    device_ip: str
    device_role: str
    in_port: str = ""
    out_port: str = ""
    member_id: int = 0
    ip_tag: int = 0
    is_up: bool = True


@dataclass
class PathResult:
    src_node_ip: str
    dst_node_ip: str
    hops: List[HopInfo] = field(default_factory=list)
    ailb_member_id_src: int = 0
    ailb_member_id_dst: int = 0
    is_ailb: bool = True
    ecmp_spines: List[str] = field(default_factory=list)
    actual_hops: List[HopInfo] = field(default_factory=list)  # ECMP实际路径
    error: str = ""

    def is_valid(self) -> bool:
        return not self.error and len(self.hops) > 0

    def summary(self) -> str:
        if self.error:
            return f"路径还原失败: {self.error}"
        if not self.is_ailb:
            return f"⚠️ AILB主路径DOWN，走ECMP，可能路径: {' / '.join(self.ecmp_spines)}"
        parts = []
        for h in self.hops:
            status = " ⚠️DOWN" if not h.is_up else ""
            name_ip = f"{h.device_name}({h.device_ip})" if h.device_name != h.device_ip else h.device_ip
            if h.in_port and h.out_port:
                parts.append(f"{name_ip}[{h.in_port}→{h.out_port}]{status}")
            elif h.out_port:
                parts.append(f"{name_ip}[→{h.out_port}]{status}")
            elif h.in_port:
                parts.append(f"{name_ip}[{h.in_port}→]{status}")
            else:
                parts.append(f"{name_ip}{status}")
        return " → ".join(parts)


class AILBAnalyzer:
    """AILB路径还原分析器"""

    def __init__(self, leaf_ips: List[str] = None):
        self.onc = ONCClient()
        self.ssh = SSHClient()
        self._config_cache: Dict[str, AILBConfig] = {}
        cfg = get_config()
        self.leaf_ips = leaf_ips or cfg.network.leaf_ips
        self.spine_ips = cfg.network.spine_ips
        self.servers = getattr(cfg.network, "servers", {}) or {}

    # ------------------------------------------------------------------
    # ONC拓扑：找server连的leaf和物理端口
    # ------------------------------------------------------------------
    def _get_topo(self, zone_id: int = 1) -> Dict:
        """获取ONC拓扑"""
        return self.onc.get_topology(zone_id)

    def _find_spine_ports(
        self, topo: Dict, device_map: Dict,
        leaf_src_id: int, leaf_src_out_port: str,
        leaf_dst_id: int, leaf_dst_in_port: str,
        spine_ip: str,
    ) -> Tuple[str, str]:
        """
        从ONC InternalLink找SPINE的入口和出口端口
        返回 (spine_in_port, spine_out_port)
        """
        spine_in_port = ""
        spine_out_port = ""

        for link in topo.get("linkList", []):
            if not isinstance(link, dict):
                continue
            if link.get("linkType") != "InternalLink":
                continue

            src_id = link.get("sourceDeviceId")
            dst_id = link.get("destDeviceId")
            src_tp = link.get("sourceTp", "")
            dst_tp = link.get("destTp", "")
            src_ip = link.get("sourceNodeIPv4", "")
            dst_ip = link.get("destNodeIPv4", "")

            # leaf_src → spine: 找leaf_src出口对应的spine入口
            if src_id == leaf_src_id and src_tp == leaf_src_out_port and dst_ip == spine_ip:
                spine_in_port = dst_tp

            # spine → leaf_dst: 找spine到leaf_dst的出口
            if src_ip == spine_ip and dst_id == leaf_dst_id and dst_tp == leaf_dst_in_port:
                spine_out_port = src_tp

        return spine_in_port, spine_out_port

    def _build_device_map(self, topo: Dict) -> Dict[int, Dict]:
        """从nodeList建立 deviceId → {name, ip} 映射"""
        result = {}
        for node in topo.get("nodeList", []):
            if isinstance(node, dict) and node.get("deviceId"):
                result[node["deviceId"]] = {
                    "name": node.get("nodeName", ""),
                    "ip": node.get("deviceIp", ""),
                    "role": node.get("nodeSubtype", ""),
                }
        return result

    def _find_server_leaf_from_topo(
        self, server_hostname: str, topo: Dict, device_map: Dict
    ) -> Optional[Tuple[str, str, str, str]]:
        """
        从ONC拓扑找server连的leaf
        返回 (leaf_ip, leaf_name, physical_port, link_status)
        优先选leaf(serverLeaf)类型
        """
        candidates = []
        for link in topo.get("linkList", []):
            if not isinstance(link, dict):
                continue
            if link.get("linkType") != "ServerDiscoverLink":
                continue

            # 从extLinkProperties找sys_name
            ext_props = link.get("extLinkProperties", [])
            sys_name = ""
            for prop in ext_props:
                if isinstance(prop, dict) and prop.get("name") == "sys_name":
                    sys_name = prop.get("value", "")
                    break
                elif isinstance(prop, str) and "sys_name" in prop:
                    m = re.search(r"value=([^;}\s]+)", prop)
                    if m:
                        sys_name = m.group(1)
                        break

            if sys_name != server_hostname:
                continue

            # 找leaf设备
            src_node = link.get("sourceNode", "")
            device_id = None
            m = re.search(r"ip:(\d+)", src_node)
            if m:
                device_id = int(m.group(1))

            if device_id and device_id in device_map:
                dev = device_map[device_id]
                if "leaf" in dev["role"].lower() or "leaf" in dev["name"].lower():
                    candidates.append((
                        dev["ip"],
                        dev["name"],
                        link.get("sourceTp", ""),
                        link.get("linkStatus", "UP"),
                    ))

        # 返回第一个UP的
        for c in candidates:
            if c[3] == "UP":
                return c
        return candidates[0] if candidates else None

    # ------------------------------------------------------------------
    # SSH：解析配置
    # ------------------------------------------------------------------
    def _get_ailb_config(self, device_ip: str) -> AILBConfig:
        """获取设备AILB配置（带缓存）"""
        if device_ip in self._config_cache:
            return self._config_cache[device_ip]

        config_text = self.ssh.get_running_config(device_ip)
        cfg = self._parse_config(device_ip, config_text)

        # LLDP获取spine hostname和UP/DOWN状态
        lldp_text = self.ssh.exec_switch(device_ip, "show lldp neighbors")
        self._parse_lldp(cfg, lldp_text, device_ip)

        # 从show run解析接口IP建立稳定的neighbor_ip→port映射（不受DOWN影响）
        self._build_neighbor_port_from_config(cfg, config_text)

        self._config_cache[device_ip] = cfg
        return cfg

    def _parse_config(self, device_ip: str, config_text: str) -> AILBConfig:
        cfg = AILBConfig(device_ip=device_ip, hostname=device_ip)

        m = re.search(r"^hostname\s+(\S+)", config_text, re.MULTILINE)
        if m:
            cfg.hostname = m.group(1)

        m = re.search(r"router bgp (\d+)", config_text)
        if m:
            cfg.bgp_as = m.group(1)

        # BGP domain member-id
        for match in re.finditer(
            r"neighbor\s+(\S+)\s+domain\s+\d+\s+member-id\s+(\d+)", config_text
        ):
            neighbor_ip = match.group(1)
            member_id = int(match.group(2))
            cfg.member_map[member_id] = neighbor_ip
            cfg.neighbor_to_member[neighbor_ip] = member_id

        # AggregatePort ip_tag
        for block in re.finditer(
            r"(interface\s+AggregatePort\s+\S+.*?)(?=\ninterface|\nrouter|\Z)",
            config_text, re.DOTALL
        ):
            text = block.group(1)
            iface_m = re.search(r"interface\s+(AggregatePort\s+\S+)", text)
            tag_m = re.search(r"ip tag\s+(\d+)", text)
            if iface_m and tag_m:
                port_name = iface_m.group(1).strip()
                cfg.port_tag_map[port_name] = int(tag_m.group(1))

        return cfg

    def _parse_lldp(self, cfg: AILBConfig, lldp_text: str, device_ip: str):
        """
        解析LLDP，建立端口→spine hostname映射和UP/DOWN状态
        注意：不用LLDP建立neighbor_ip→port映射（DOWN端口不出现在LLDP）
        neighbor_ip→port映射由_build_neighbor_port_from_config完成
        """
        for line in lldp_text.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            if parts[0] in ("System", "Capability", "(R)", "(B)", "Total"):
                continue
            neighbor_name = parts[0]
            local_port = parts[1]
            if "spine" in neighbor_name.lower():
                cfg.port_to_spine[local_port] = neighbor_name
                cfg.port_status[local_port] = True  # LLDP有就是UP

    def _build_neighbor_port_from_config(self, cfg: AILBConfig, config_text: str):
        """
        从show run解析接口IP，建立稳定的neighbor_ip→port映射
        不依赖LLDP，DOWN的端口也能正确映射
        接口本端IP和对端neighbor IP的关系：/30子网，本端偶数对端奇数(本端-1)
        """
        for block in re.finditer(r"(interface\s+FH\S+.*?)(?=\ninterface|\nrouter|\Z)", config_text, re.DOTALL):
            text = block.group(1)
            iface_m = re.search(r"interface\s+(FH\S+)", text)
            ip_m = re.search(r"ip address\s+(\S+)\s+(\S+)", text)
            if not iface_m or not ip_m:
                continue
            port_name = iface_m.group(1)
            local_ip = ip_m.group(1)
            mask = ip_m.group(2)
            peer_ip = self._calc_peer_ip(local_ip, mask)
            if peer_ip and peer_ip in cfg.neighbor_to_member:
                cfg.neighbor_to_port[peer_ip] = port_name
                # 如果LLDP里没有这个端口，说明它DOWN了
                if port_name not in cfg.port_to_spine:
                    cfg.port_status[port_name] = False

    def _calc_peer_ip(self, local_ip: str, mask: str) -> str:
        """计算/30或/31子网的对端IP"""
        try:
            parts = list(map(int, local_ip.split(".")))
            if mask == "255.255.255.254":  # /31
                parts[-1] ^= 1
            elif mask == "255.255.255.252":  # /30
                if parts[-1] % 2 == 0:
                    parts[-1] -= 1
                else:
                    parts[-1] += 1
            else:
                return ""
            return ".".join(map(str, parts))
        except Exception:
            return ""

    def _get_actual_route(self, leaf_ip: str, dst_ip: str) -> dict:
        """
        查leaf上到dst_ip的实际路由
        返回 {
          "type": "local/spine/blackhole",
          "via": "172.17.0.9",
          "interface": "FHGigabitEthernet 0/67",
          "raw": "..."
        }
        """
        try:
            output = self.ssh.exec_switch(leaf_ip, f"show ip route {dst_ip}")

            # /32主机路由 via VLAN → 本地转发
            if "ARPHOST" in output or ("via VLAN" in output and "VLAN" in output):
                return {"type": "local", "via": "", "interface": "", "raw": output}

            # /32路由 格式: "172.17.0.9, 21:22:50 ago, via FHGigabitEthernet 0/67"
            m = re.search(r"([\d.]+),\s+\S+\s+ago,\s+via\s+(FH\S+\s+[\d/]+)", output)
            if m:
                via_ip = m.group(1)
                interface = m.group(2)
                return {"type": "spine", "via": via_ip, "interface": interface, "raw": output}

            # 没有/32，查/24网段
            parts = dst_ip.split(".")
            net24 = f"{parts[0]}.{parts[1]}.{parts[2]}.0"
            output2 = self.ssh.exec_switch(leaf_ip, f"show ip route {net24}")

            if "directly connected" in output2:
                return {"type": "local", "via": "", "interface": "", "raw": output2}

            m2 = re.search(r"([\d.]+),\s+\S+\s+ago,\s+via\s+(FH\S+\s+[\d/]+)", output2)
            if m2:
                via_ip = m2.group(1)
                interface = m2.group(2)
                return {"type": "spine", "via": via_ip, "interface": interface, "raw": output2}

            return {"type": "blackhole", "via": "", "interface": "", "raw": output}
        except Exception as e:
            return {"type": "unknown", "via": "", "interface": "", "raw": str(e)}

    def _check_route(self, leaf_ip: str, dst_ip: str) -> str:
        """
        查leaf上到dst_ip的路由
        返回:
          "local"  → leaf本地转发（ARPHOST/直连），不经过spine
          "spine"  → 需要经过spine
          "unknown" → 无法判断
        """
        try:
            output = self.ssh.exec_switch(leaf_ip, f"show ip route {dst_ip}")
            if "ARPHOST" in output or "via VLAN" in output:
                return "local"
            if "via 172." in output or "via 10." in output:
                return "spine"
            # 默认走AILB逻辑
            return "spine"
        except Exception:
            return "spine"

    def _get_aggregate_port(self, leaf_ip: str, physical_port: str) -> Optional[str]:
        """
        查physical_port属于哪个AggregatePort
        show run interface FH0/9:1 → port-group 145 → AggregatePort 145
        """
        port_name = physical_port.replace("FH", "FHGigabitEthernet ").replace("0/", "0/")
        output = self.ssh.exec_switch(leaf_ip, f"show run interface {port_name}")
        m = re.search(r"port-group\s+(\d+)", output)
        if m:
            return f"AggregatePort {m.group(1)}"
        return None

    def _get_ip_tag(self, leaf_ip: str, agg_port: str) -> Optional[int]:
        """从AggregatePort配置里找ip_tag"""
        output = self.ssh.exec_switch(leaf_ip, f"show run interface {agg_port}")
        m = re.search(r"ip tag\s+(\d+)", output)
        if m:
            return int(m.group(1))
        return None

    # ------------------------------------------------------------------
    # 主路径还原
    # ------------------------------------------------------------------
    def resolve_path(
        self,
        src_node_ip: str,
        dst_node_ip: str,
        mode: str = None,
        zone_id: int = None,
        force_refresh: bool = False,
    ) -> PathResult:
        if mode is None:
            mode = get_config().network.topology_mode
        if zone_id is None:
            zone_id = get_config().network.zone_id
        return self._resolve(src_node_ip, dst_node_ip, zone_id)

    def _resolve(self, src_node_ip: str, dst_node_ip: str, zone_id: int = 1) -> PathResult:
        result = PathResult(src_node_ip=src_node_ip, dst_node_ip=dst_node_ip)

        try:
            # Step1: 从config找server hostname
            src_hostname = self.servers.get(src_node_ip, "")
            dst_hostname = self.servers.get(dst_node_ip, "")
            if not src_hostname or not dst_hostname:
                result.error = (
                    f"请在config.yaml的network.servers里配置server IP→hostname映射\n"
                    f"缺少: {src_node_ip if not src_hostname else dst_node_ip}"
                )
                return result

            # Step2: ONC拓扑找server-leaf连接
            topo = self._get_topo(zone_id)
            device_map = self._build_device_map(topo)

            src_leaf_info = self._find_server_leaf_from_topo(src_hostname, topo, device_map)
            if not src_leaf_info:
                result.error = f"ONC拓扑中找不到 {src_hostname} 连接的Leaf"
                return result
            leaf_src_ip, leaf_src_name, src_physical_port, src_link_status = src_leaf_info

            dst_leaf_info = self._find_server_leaf_from_topo(dst_hostname, topo, device_map)
            if not dst_leaf_info:
                result.error = f"ONC拓扑中找不到 {dst_hostname} 连接的Leaf"
                return result
            leaf_dst_ip, leaf_dst_name, dst_physical_port, dst_link_status = dst_leaf_info

            # Step2.5: 查路由表判断是否需要经过spine
            route_info = self._check_route(leaf_src_ip, dst_node_ip)
            if route_info == "local":
                # leaf本地转发，不经过spine
                result.is_ailb = False
                src_agg_port_local = self._get_aggregate_port(leaf_src_ip, src_physical_port)
                dst_agg_port_local = self._get_aggregate_port(leaf_dst_ip, dst_physical_port)
                src_tag_local = self._get_ip_tag(leaf_src_ip, src_agg_port_local) if src_agg_port_local else 0
                dst_tag_local = self._get_ip_tag(leaf_dst_ip, dst_agg_port_local) if dst_agg_port_local else 0
                result.hops = [
                    HopInfo(
                        device_name=src_hostname, device_ip=src_node_ip,
                        device_role="server", out_port=src_agg_port_local or src_physical_port,
                        ip_tag=src_tag_local or 0,
                    ),
                    HopInfo(
                        device_name=leaf_src_name, device_ip=leaf_src_ip,
                        device_role="leaf",
                        in_port=src_agg_port_local or src_physical_port,
                        out_port=dst_agg_port_local or dst_physical_port,
                    ),
                    HopInfo(
                        device_name=dst_hostname, device_ip=dst_node_ip,
                        device_role="server", in_port=dst_agg_port_local or dst_physical_port,
                        ip_tag=dst_tag_local or 0,
                    ),
                ]
                return result

            # Step3: 找AggregatePort和ip_tag
            src_agg_port = self._get_aggregate_port(leaf_src_ip, src_physical_port)
            if not src_agg_port:
                result.error = f"找不到 {src_physical_port} 对应的AggregatePort"
                return result

            dst_agg_port = self._get_aggregate_port(leaf_dst_ip, dst_physical_port)
            if not dst_agg_port:
                result.error = f"找不到 {dst_physical_port} 对应的AggregatePort"
                return result

            src_tag = self._get_ip_tag(leaf_src_ip, src_agg_port)
            dst_tag = self._get_ip_tag(leaf_dst_ip, dst_agg_port)

            if src_tag is None or dst_tag is None:
                result.error = f"找不到ip_tag: src={src_tag} dst={dst_tag}"
                return result

            # Step4: 读取AILB配置
            ailb_src = self._get_ailb_config(leaf_src_ip)
            ailb_dst = self._get_ailb_config(leaf_dst_ip)

            # Step5: AILB计算
            member_id_src = ailb_src.calc_member_id(dst_tag)
            member_id_dst = ailb_dst.calc_member_id(src_tag)

            result.ailb_member_id_src = member_id_src
            result.ailb_member_id_dst = member_id_dst

            # Step6: 找SPINE上行端口
            spine_neighbor_ip = ailb_src.member_map.get(member_id_src, "")
            spine_out_port = ailb_src.neighbor_to_port.get(spine_neighbor_ip, "")
            spine_is_up = ailb_src.port_status.get(spine_out_port, True)
            spine_hostname = ailb_src.port_to_spine.get(spine_out_port, spine_neighbor_ip)

            # 找SPINE的IP
            spine_ip = spine_neighbor_ip
            for node in topo.get("nodeList", []):
                if isinstance(node, dict) and node.get("nodeName") == spine_hostname:
                    spine_ip = node.get("deviceIp", spine_neighbor_ip)
                    break

            # Step7: 检查主路径UP/DOWN
            if not spine_is_up:
                result.is_ailb = False
                for port, hostname in ailb_src.port_to_spine.items():
                    if ailb_src.port_status.get(port, True):
                        result.ecmp_spines.append(hostname)

            # Step8: 找LEAF_dst入向端口（SPINE→LEAF_dst）
            spine_in_port_dst = ailb_dst.neighbor_to_port.get(
                ailb_dst.member_map.get(member_id_dst, ""), ""
            )

            # Step8.5: 路由表验证 vs AILB计算
            actual_route = self._get_actual_route(leaf_src_ip, dst_node_ip)
            route_interface = actual_route.get("interface", "")
            ailb_interface = spine_out_port

            if actual_route["type"] == "blackhole":
                result.error = f"路由黑洞：leaf1({leaf_src_ip})上没有到{dst_node_ip}的路由"
                return result
            elif actual_route["type"] == "local":
                # 本地转发，不经过spine
                result.is_ailb = False
                result.hops = [
                    HopInfo(device_name=src_hostname, device_ip=src_node_ip,
                            device_role="server", out_port=src_agg_port, ip_tag=src_tag),
                    HopInfo(device_name=leaf_src_name, device_ip=leaf_src_ip,
                            device_role="leaf", in_port=src_agg_port, out_port=dst_agg_port),
                    HopInfo(device_name=dst_hostname, device_ip=dst_node_ip,
                            device_role="server", in_port=dst_agg_port, ip_tag=dst_tag),
                ]
                return result
            # 保存AILB理论端口（不被实际路由覆盖）
            ailb_spine_out_port = spine_out_port  # AILB理论出口（如FH0/67）
            ailb_spine_is_up = spine_is_up
            actual_spine_out_port = spine_out_port  # 实际出口，默认同理论
            actual_spine_hostname = spine_hostname
            actual_spine_ip = spine_ip
            is_ecmp = False

            if actual_route["type"] == "spine" and route_interface and ailb_interface:
                ri = route_interface.replace("GigabitEthernet ", "").replace("FHGigabit", "FH").replace(" ", "")
                ai = ailb_interface.replace("GigabitEthernet ", "").replace("FHGigabit", "FH").replace(" ", "")
                if ri != ai:
                    # 不一致，走了ECMP
                    is_ecmp = True
                    result.is_ailb = False
                    ailb_spine_is_up = False
                    actual_spine_out_port = route_interface
                    actual_spine_hostname = ailb_src.port_to_spine.get(route_interface, actual_route["via"])
                    # 找实际spine IP
                    for node in topo.get("nodeList", []):
                        if isinstance(node, dict) and node.get("nodeName") == actual_spine_hostname:
                            actual_spine_ip = node.get("deviceIp", spine_ip)
                            break
                    # 收集所有可用spine（去重）
                    seen = set()
                    for port, hostname in ailb_src.port_to_spine.items():
                        if hostname not in seen:
                            seen.add(hostname)
                            result.ecmp_spines.append(hostname)

            # Step9: 从ONC拿SPINE出入端口（AILB理论路径用）
            leaf_src_device_id = next(
                (k for k, v in device_map.items() if v["ip"] == leaf_src_ip), None
            )
            leaf_dst_device_id = next(
                (k for k, v in device_map.items() if v["ip"] == leaf_dst_ip), None
            )
            # AILB理论路径的SPINE端口
            ailb_spine_in_port, ailb_spine_out_to_dst = self._find_spine_ports(
                topo, device_map,
                leaf_src_device_id, ailb_spine_out_port,
                leaf_dst_device_id, spine_in_port_dst,
                spine_ip,
            )
            # 实际路径的SPINE端口
            actual_spine_in_port, actual_spine_out_to_dst = self._find_spine_ports(
                topo, device_map,
                leaf_src_device_id, actual_spine_out_port,
                leaf_dst_device_id, spine_in_port_dst,
                actual_spine_ip,
            )
            # 实际路径leaf_dst入口
            actual_spine_in_port_dst = spine_in_port_dst
            if is_ecmp and actual_spine_out_to_dst:
                actual_spine_in_port_dst = actual_spine_out_to_dst

            # Step10: 组装AILB理论路径
            result.hops = [
                HopInfo(
                    device_name=src_hostname, device_ip=src_node_ip,
                    device_role="server", out_port=src_agg_port,
                    ip_tag=src_tag, is_up=(src_link_status == "UP"),
                ),
                HopInfo(
                    device_name=leaf_src_name, device_ip=leaf_src_ip,
                    device_role="leaf", in_port=src_agg_port,
                    out_port=ailb_spine_out_port, member_id=member_id_src,
                    is_up=ailb_spine_is_up,
                ),
                HopInfo(
                    device_name=spine_hostname, device_ip=spine_ip,
                    device_role="spine",
                    in_port=ailb_spine_in_port,
                    out_port=ailb_spine_out_to_dst,
                    is_up=ailb_spine_is_up,
                ),
                HopInfo(
                    device_name=leaf_dst_name, device_ip=leaf_dst_ip,
                    device_role="leaf", in_port=spine_in_port_dst,
                    out_port=dst_agg_port, member_id=member_id_dst,
                    is_up=ailb_spine_is_up,
                ),
                HopInfo(
                    device_name=dst_hostname, device_ip=dst_node_ip,
                    device_role="server", in_port=dst_agg_port,
                    ip_tag=dst_tag, is_up=(dst_link_status == "UP"),
                ),
            ]

            # Step11: 如果ECMP，组装实际路径
            if is_ecmp:
                result.actual_hops = [
                    HopInfo(
                        device_name=src_hostname, device_ip=src_node_ip,
                        device_role="server", out_port=src_agg_port,
                        ip_tag=src_tag,
                    ),
                    HopInfo(
                        device_name=leaf_src_name, device_ip=leaf_src_ip,
                        device_role="leaf", in_port=src_agg_port,
                        out_port=actual_spine_out_port, member_id=member_id_src,
                    ),
                    HopInfo(
                        device_name=actual_spine_hostname, device_ip=actual_spine_ip,
                        device_role="spine",
                        in_port=actual_spine_in_port,
                        out_port=actual_spine_out_to_dst,
                    ),
                    HopInfo(
                        device_name=leaf_dst_name, device_ip=leaf_dst_ip,
                        device_role="leaf", in_port=actual_spine_in_port_dst,
                        out_port=dst_agg_port, member_id=member_id_dst,
                    ),
                    HopInfo(
                        device_name=dst_hostname, device_ip=dst_node_ip,
                        device_role="server", in_port=dst_agg_port,
                        ip_tag=dst_tag,
                    ),
                ]

        except Exception as e:
            import traceback
            result.error = f"{e}\n{traceback.format_exc()}"

        return result
