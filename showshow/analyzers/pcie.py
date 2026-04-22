"""
PCIe/NVLink 拓扑分析
通过SSH执行 nvidia-smi topo -m 获取GPU与NIC的拓扑关系
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from showshow.adapters.ssh import SSHClient


@dataclass
class GPUInfo:
    index: int
    bus_id: str = ""
    pcie_gen_current: str = ""
    pcie_gen_max: str = ""
    pcie_width_current: str = ""
    pcie_width_max: str = ""

    @property
    def pcie_degraded(self) -> bool:
        """PCIe是否降速"""
        return (
            self.pcie_gen_current and self.pcie_gen_max
            and self.pcie_gen_current != self.pcie_gen_max
        ) or (
            self.pcie_width_current and self.pcie_width_max
            and self.pcie_width_current != self.pcie_width_max
        )

    @property
    def pcie_summary(self) -> str:
        if self.pcie_gen_current:
            current = f"Gen{self.pcie_gen_current}x{self.pcie_width_current}"
            max_ = f"Gen{self.pcie_gen_max}x{self.pcie_width_max}"
            if self.pcie_degraded:
                return f"{current} ⚠️ (最大{max_})"
            return f"{current}"
        return "未知"


@dataclass
class PCIeTopology:
    """服务器PCIe拓扑"""
    node_ip: str
    raw_topo: str = ""
    gpus: List[GPUInfo] = field(default_factory=list)
    # GPU到NIC的关系：{gpu_index: connection_type}
    # connection_type: NV1/NV2/NV4(NVLink) / PHB(PCIe) / NODE / SYS
    gpu_nic_relations: Dict[str, str] = field(default_factory=dict)
    error: str = ""

    def has_degraded_pcie(self) -> bool:
        return any(g.pcie_degraded for g in self.gpus)

    def summary(self) -> str:
        if self.error:
            return f"PCIe拓扑获取失败: {self.error}"
        lines = []
        for gpu in self.gpus:
            status = "⚠️ PCIe降速" if gpu.pcie_degraded else "✓"
            lines.append(f"  GPU{gpu.index} [{gpu.bus_id}] {gpu.pcie_summary} {status}")
        return "\n".join(lines) if lines else "无GPU信息"


class PCIeAnalyzer:
    """PCIe拓扑分析器"""

    def __init__(self):
        self.ssh = SSHClient()

    def get_topology(self, node_ip: str) -> PCIeTopology:
        topo = PCIeTopology(node_ip=node_ip)
        try:
            # 获取拓扑矩阵
            topo.raw_topo = self.ssh.get_pcie_topology(node_ip)
            # 获取PCIe带宽信息
            bw_output = self.ssh.get_pcie_bandwidth(node_ip)
            topo.gpus = self._parse_pcie_bandwidth(bw_output)
            # 解析GPU-NIC关系
            topo.gpu_nic_relations = self._parse_nic_relations(topo.raw_topo)
        except Exception as e:
            topo.error = str(e)
        return topo

    def _parse_pcie_bandwidth(self, output: str) -> List[GPUInfo]:
        """
        解析 nvidia-smi --query-gpu=index,pcie.link.gen.current,
        pcie.link.width.current,pcie.link.gen.max,pcie.link.width.max
        """
        gpus = []
        for line in output.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                try:
                    gpus.append(GPUInfo(
                        index=int(parts[0]),
                        pcie_gen_current=parts[1],
                        pcie_width_current=parts[2],
                        pcie_gen_max=parts[3],
                        pcie_width_max=parts[4],
                    ))
                except (ValueError, IndexError):
                    continue
        return gpus

    def _parse_nic_relations(self, topo_output: str) -> Dict[str, str]:
        """
        解析 nvidia-smi topo -m 输出
        找到GPU和mlx/enp等NIC的连接关系
        返回 {nic_name: {gpu_index: connection_type}}
        """
        relations = {}
        lines = topo_output.strip().splitlines()
        if not lines:
            return relations

        # 找header行（包含GPU0 GPU1 ...）
        header_line = None
        for line in lines:
            if "GPU" in line and ("CPU" in line or "NIC" in line or "mlx" in line.lower()):
                header_line = line
                break

        # 解析NIC行（包含mlx或enp等关键字）
        for line in lines:
            lower = line.lower()
            if any(k in lower for k in ["mlx", "enp", "ib", "rdma"]):
                parts = line.split()
                if parts:
                    nic_name = parts[0]
                    relations[nic_name] = line.strip()

        return relations
