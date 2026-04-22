"""
ShowShow 巡检项定义
预防性检查主机和网络配置
"""

import re
from dataclasses import dataclass
from typing import List, Optional
from showshow.adapters.ssh import SSHClient
from showshow.adapters.onc import ONCClient


@dataclass
class CheckResult:
    node_ip: str
    check_name: str
    status: str         # pass / warning / fail
    expected: str = ""
    actual: str = ""
    suggestion: str = ""


class Inspector:
    def __init__(self):
        self.ssh = SSHClient()
        self.onc = ONCClient()

    def run(
        self,
        node_list: Optional[List[str]] = None,
        scope: str = "all",
    ) -> List[CheckResult]:
        results = []

        if scope in ("host", "all"):
            servers = node_list or self._get_all_server_ips()
            for ip in servers:
                results.extend(self._check_host(ip))

        if scope in ("network", "all"):
            results.extend(self._check_network())

        return results

    def _get_all_server_ips(self) -> List[str]:
        servers = self.onc.get_servers()
        return [s["deviceIp"] for s in servers if s.get("deviceIp")]

    # ------------------------------------------------------------------
    # 主机侧检查
    # ------------------------------------------------------------------
    def _check_host(self, ip: str) -> List[CheckResult]:
        results = []
        try:
            # CPU模式
            cpu_gov = self.ssh.exec(ip, "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").strip()
            results.append(CheckResult(
                node_ip=ip, check_name="CPU高性能模式",
                status="pass" if cpu_gov == "performance" else "fail",
                expected="performance", actual=cpu_gov,
                suggestion="执行: cpupower frequency-set -g performance",
            ))

            # iommu
            iommu = self.ssh.exec(ip, "cat /proc/cmdline")
            iommu_disabled = "iommu=off" in iommu or "intel_iommu=off" in iommu
            results.append(CheckResult(
                node_ip=ip, check_name="iommu已关闭",
                status="pass" if iommu_disabled else "warning",
                expected="iommu=off", actual="已关闭" if iommu_disabled else "未关闭",
                suggestion="在/etc/default/grub中添加 iommu=off",
            ))

            # nouveau禁用
            nouveau = self.ssh.exec(ip, "lsmod | grep nouveau").strip()
            results.append(CheckResult(
                node_ip=ip, check_name="nouveau驱动已禁用",
                status="pass" if not nouveau else "fail",
                expected="未加载", actual="未加载" if not nouveau else "已加载",
                suggestion="echo 'blacklist nouveau' >> /etc/modprobe.d/blacklist.conf",
            ))

            # ECC跳变
            ecc = self.ssh.exec(ip, "nvidia-smi --query-gpu=ecc.errors.uncorrected.volatile.total --format=csv,noheader").strip()
            for line in ecc.splitlines():
                val = line.strip()
                try:
                    ecc_count = int(val)
                    results.append(CheckResult(
                        node_ip=ip, check_name="GPU ECC跳变",
                        status="pass" if ecc_count == 0 else "warning",
                        expected="0", actual=str(ecc_count),
                        suggestion="检查GPU硬件，联系厂商" if ecc_count > 0 else "",
                    ))
                except ValueError:
                    pass

            # PCIe降速
            bw = self.ssh.exec(
                ip,
                "nvidia-smi --query-gpu=index,pcie.link.gen.current,pcie.link.width.current,"
                "pcie.link.gen.max,pcie.link.width.max --format=csv,noheader"
            )
            for line in bw.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    idx, gen_cur, width_cur, gen_max, width_max = parts[:5]
                    degraded = gen_cur != gen_max or width_cur != width_max
                    results.append(CheckResult(
                        node_ip=ip, check_name=f"GPU{idx} PCIe带宽",
                        status="warning" if degraded else "pass",
                        expected=f"Gen{gen_max}x{width_max}",
                        actual=f"Gen{gen_cur}x{width_cur}",
                        suggestion="检查PCIe插槽或重新插拔GPU" if degraded else "",
                    ))

        except Exception as e:
            results.append(CheckResult(
                node_ip=ip, check_name="SSH连接",
                status="fail",
                actual=str(e),
                suggestion="检查SSH凭证配置",
            ))

        return results

    # ------------------------------------------------------------------
    # 网络侧检查
    # ------------------------------------------------------------------
    def _check_network(self) -> List[CheckResult]:
        results = []
        try:
            switches = self.onc.get_switches()
            for sw in switches:
                ip = sw.get("deviceIp", "")
                name = sw.get("deviceName", ip)
                if not ip:
                    continue

                # 查告警：PFC storm
                alerts = self.onc.get_active_alerts(device_ip=ip)
                pfc_alerts = [a for a in alerts if "PFC" in a.get("message", "")]
                if pfc_alerts:
                    results.append(CheckResult(
                        node_ip=ip, check_name=f"[{name}] PFC告警",
                        status="warning",
                        actual=f"{len(pfc_alerts)}条PFC告警",
                        suggestion="检查拥塞配置和流量模型",
                    ))
        except Exception as e:
            results.append(CheckResult(
                node_ip="network", check_name="网络巡检",
                status="fail", actual=str(e),
            ))

        return results
