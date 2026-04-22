"""
指标拉取和异常判定
针对路径上每个节点拉取PFC/ECN/丢包等指标，标记异常
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from showshow.adapters.onc import ONCClient
from showshow.core.indicators import PORT, QUEUE, NIC, NIC_QUEUE
from showshow.core.config import get_config


@dataclass
class MetricPoint:
    timestamp: int
    value: float
    unit: str = ""


@dataclass
class NodeMetrics:
    """单个节点/端口的指标数据"""
    device_ip: str
    device_name: str
    device_role: str    # server / leaf / spine
    port: str = ""

    # 关键指标最新值
    pfc_send: float = 0
    pfc_recv: float = 0
    pfc_send_rate: float = 0
    pfc_recv_rate: float = 0
    ecn_marked: float = 0
    ecn_rate: float = 0
    tx_drop: float = 0
    rx_drop: float = 0
    wred_drop: float = 0
    headroom_used: float = 0    # %
    nak_tx: float = 0
    nak_rx: float = 0
    cnp_tx: float = 0
    cnp_rx: float = 0

    # 异常标记
    anomalies: List[str] = field(default_factory=list)

    def has_anomaly(self) -> bool:
        return len(self.anomalies) > 0


# 异常判定阈值（可后续做成可配置）
THRESHOLDS = {
    "pfc_send_rate":  100,     # PFC发送速率 >100pps 告警
    "pfc_recv_rate":  100,
    "ecn_rate":       1000,    # ECN标记速率 >1000pps
    "tx_drop":        0,       # 有丢包即告警
    "rx_drop":        0,
    "wred_drop":      0,
    "headroom_used":  80.0,    # headroom占用率 >80%
    "nak_tx":         0,
    "nak_rx":         0,
}


def _latest_value(data_points: List[Dict]) -> float:
    """取最新一个数据点的值"""
    if not data_points:
        return 0
    latest = max(data_points, key=lambda x: x.get("timestamp", 0))
    indicators = latest.get("indicatorList", [])
    if indicators:
        return float(indicators[0].get("doubleValue") or indicators[0].get("longValue") or 0)
    return 0


class MetricsAnalyzer:
    """路径指标分析器"""

    def __init__(self):
        self.onc = ONCClient()
        self.cfg = get_config()

    def _get_device_id(self, device_ip: str) -> Optional[int]:
        """通过IP查ONC设备ID"""
        device = self.onc.find_device_by_ip(device_ip)
        if device:
            return device.get("id")
        return None

    def analyze_switch_port(
        self,
        device_ip: str,
        device_name: str,
        device_role: str,
        port: str,
        start_time: int,
        end_time: int,
    ) -> NodeMetrics:
        """分析交换机端口指标"""
        metrics = NodeMetrics(
            device_ip=device_ip,
            device_name=device_name,
            device_role=device_role,
            port=port,
        )

        device_id = self._get_device_id(device_ip)
        if not device_id:
            metrics.anomalies.append(f"设备 {device_ip} 在ONC中未找到")
            return metrics

        p = self.cfg.network.roce_priority  # RoCE Priority，默认P3

        # 批量拉取指标
        indicate_ids = [
            PORT["ecn_marked"],
            PORT["ecn_rate"],
            PORT["wred_drop"],
            PORT["tx_drop_pkts"],
            PORT["rx_drop_pkts"],
            PORT["headroom_used"],
            PORT["nak_tx"],
            PORT["nak_rx"],
            PORT["cnp_tx"],
            PORT["cnp_rx"],
            QUEUE["pfc_send"][p],
            QUEUE["pfc_recv"][p],
            QUEUE["pfc_send_rate"][p],
            QUEUE["pfc_recv_rate"][p],
            QUEUE["unicast_drop_pkts"][p],
        ]

        results = self.onc.get_indicators_batch(
            device_id, indicate_ids, port=port,
            start_time=start_time, end_time=end_time
        )

        metrics.ecn_marked    = _latest_value(results.get(PORT["ecn_marked"], []))
        metrics.ecn_rate      = _latest_value(results.get(PORT["ecn_rate"], []))
        metrics.wred_drop     = _latest_value(results.get(PORT["wred_drop"], []))
        metrics.tx_drop       = _latest_value(results.get(PORT["tx_drop_pkts"], []))
        metrics.rx_drop       = _latest_value(results.get(PORT["rx_drop_pkts"], []))
        metrics.headroom_used = _latest_value(results.get(PORT["headroom_used"], []))
        metrics.nak_tx        = _latest_value(results.get(PORT["nak_tx"], []))
        metrics.nak_rx        = _latest_value(results.get(PORT["nak_rx"], []))
        metrics.cnp_tx        = _latest_value(results.get(PORT["cnp_tx"], []))
        metrics.cnp_rx        = _latest_value(results.get(PORT["cnp_rx"], []))
        metrics.pfc_send      = _latest_value(results.get(QUEUE["pfc_send"][p], []))
        metrics.pfc_recv      = _latest_value(results.get(QUEUE["pfc_recv"][p], []))
        metrics.pfc_send_rate = _latest_value(results.get(QUEUE["pfc_send_rate"][p], []))
        metrics.pfc_recv_rate = _latest_value(results.get(QUEUE["pfc_recv_rate"][p], []))

        self._check_anomalies(metrics)
        return metrics

    def analyze_nic(
        self,
        device_ip: str,
        device_name: str,
        nic_name: str,
        start_time: int,
        end_time: int,
    ) -> NodeMetrics:
        """分析服务器网卡指标"""
        metrics = NodeMetrics(
            device_ip=device_ip,
            device_name=device_name,
            device_role="server",
            port=nic_name,
        )

        device_id = self._get_device_id(device_ip)
        if not device_id:
            metrics.anomalies.append(f"设备 {device_ip} 在ONC中未找到")
            return metrics

        p = self.cfg.network.roce_priority

        indicate_ids = [
            NIC["rx_pfc"],
            NIC["tx_pfc"],
            NIC["rx_cnp"],
            NIC["tx_cnp"],
            NIC["ecn_marked"],
            NIC["ecn_marked_rate"],
            NIC["rx_pfc_rate"],
            NIC["tx_pfc_rate"],
            NIC["out_of_buffer"],
            NIC["rx_drop"],
            NIC["tx_drop"],
            NIC["rnr_nak"],
            NIC["nak_seq_err"],
            NIC_QUEUE["rx_pause"][p],
            NIC_QUEUE["tx_pause"][p],
            NIC_QUEUE["rx_cong_discard"][p],
            NIC_QUEUE["ecn_marked"][p],
        ]

        results = self.onc.get_indicators_batch(
            device_id, indicate_ids, port=nic_name,
            start_time=start_time, end_time=end_time
        )

        metrics.pfc_recv      = _latest_value(results.get(NIC["rx_pfc"], []))
        metrics.pfc_send      = _latest_value(results.get(NIC["tx_pfc"], []))
        metrics.pfc_recv_rate = _latest_value(results.get(NIC["rx_pfc_rate"], []))
        metrics.pfc_send_rate = _latest_value(results.get(NIC["tx_pfc_rate"], []))
        metrics.cnp_rx        = _latest_value(results.get(NIC["rx_cnp"], []))
        metrics.cnp_tx        = _latest_value(results.get(NIC["tx_cnp"], []))
        metrics.ecn_marked    = _latest_value(results.get(NIC["ecn_marked"], []))
        metrics.ecn_rate      = _latest_value(results.get(NIC["ecn_marked_rate"], []))
        metrics.rx_drop       = _latest_value(results.get(NIC["rx_drop"], []))
        metrics.tx_drop       = _latest_value(results.get(NIC["tx_drop"], []))
        metrics.nak_rx        = _latest_value(results.get(NIC["rnr_nak"], []))

        self._check_anomalies(metrics)
        return metrics

    def _check_anomalies(self, metrics: NodeMetrics):
        """根据阈值判定异常"""
        checks = [
            ("pfc_send_rate", metrics.pfc_send_rate, f"PFC发送速率过高: {metrics.pfc_send_rate:.0f}pps"),
            ("pfc_recv_rate", metrics.pfc_recv_rate, f"PFC接收速率过高: {metrics.pfc_recv_rate:.0f}pps"),
            ("ecn_rate",      metrics.ecn_rate,      f"ECN标记速率过高: {metrics.ecn_rate:.0f}pps"),
            ("tx_drop",       metrics.tx_drop,        f"发送丢包: {metrics.tx_drop:.0f}包"),
            ("rx_drop",       metrics.rx_drop,        f"接收丢包: {metrics.rx_drop:.0f}包"),
            ("wred_drop",     metrics.wred_drop,       f"WRED丢包: {metrics.wred_drop:.0f}包"),
            ("headroom_used", metrics.headroom_used,   f"Headroom占用率过高: {metrics.headroom_used:.1f}%"),
            ("nak_tx",        metrics.nak_tx,          f"发送NAK: {metrics.nak_tx:.0f}"),
            ("nak_rx",        metrics.nak_rx,          f"接收NAK: {metrics.nak_rx:.0f}"),
        ]
        for key, value, msg in checks:
            threshold = THRESHOLDS.get(key, 0)
            if value > threshold:
                metrics.anomalies.append(msg)
