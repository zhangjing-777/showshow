"""ONC REST API 封装 - 适配 HTTPS + RSA+password 认证"""
import time
import base64
import requests
import urllib3
from typing import Any, Dict, List, Optional
from showshow.core.config import get_config

# 禁用自签证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ONC登录固定参数
_ONC_CLIENT_AUTH = "Basic d2ViX2FwcDpyZ3Nkbg=="   # web_app:rgsdbn，固定
_ONC_USERNAME    = "admin"
_ONC_PASSWORD    = "Ruijie@123"


def _rsa_encrypt(public_key_b64: str, plaintext: str) -> str:
    """用ONC返回的RSA公钥加密明文，返回Base64密文"""
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_v1_5

    pem = (
        "-----BEGIN PUBLIC KEY-----\n"
        + public_key_b64
        + "\n-----END PUBLIC KEY-----"
    )
    key = RSA.import_key(pem)
    cipher = PKCS1_v1_5.new(key)
    encrypted = cipher.encrypt(plaintext.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


class ONCClient:
    """ONC分析器北向REST API客户端"""

    def __init__(self):
        self.cfg = get_config().onc
        self._token: Optional[str] = None
        self._token_expire: float = 0
        self._session = requests.Session()
        self._session.verify = False   # 跳过自签证书

    # ------------------------------------------------------------------
    # 鉴权
    # ------------------------------------------------------------------
    def _get_public_key(self) -> str:
        """获取RSA公钥"""
        resp = self._session.get(
            f"{self.cfg.base_url}/uaa/api/v1/rsa/public",
            timeout=self.cfg.timeout,
        )
        resp.raise_for_status()
        return resp.json()["publicKey"]

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expire:
            return self._token

        # Step1: 拿公钥
        pub_key = self._get_public_key()

        # Step2: RSA加密密码
        encrypted_password = _rsa_encrypt(pub_key, _ONC_PASSWORD)

        # Step3: 登录
        resp = self._session.post(
            f"{self.cfg.base_url}/auth/token",
            headers={"Authorization": _ONC_CLIENT_AUTH},
            data={
                "username": _ONC_USERNAME,
                "password": encrypted_password,
                "grant_type": "password",
                "encrypt": "true",
            },
            timeout=self.cfg.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expire = time.time() + data.get("expires_in", 604800) - 60
        return self._token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: Dict = None) -> Any:
        resp = self._session.get(
            f"{self.cfg.base_url}{path}",
            headers=self._headers(),
            params=params or {},
            timeout=self.cfg.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: Dict) -> Any:
        resp = self._session.post(
            f"{self.cfg.base_url}{path}",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=body,
            timeout=self.cfg.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # 设备管理
    # ------------------------------------------------------------------
    def get_all_devices(self, is_server: bool = False) -> List[Dict]:
        """获取所有设备列表（自动翻页）"""
        devices = []
        page = 0
        size = 100
        while True:
            data = self._get(
                "/ne-mgr/v2/device/query",
                params={"page": page, "size": size, "isServer": str(is_server).lower()},
            )
            items = data.get("items", [])
            devices.extend(items)
            if page + 1 >= data.get("totalPage", 1):
                break
            page += 1
        return devices

    def get_servers(self) -> List[Dict]:
        return self.get_all_devices(is_server=True)

    def get_switches(self) -> List[Dict]:
        return self.get_all_devices(is_server=False)

    def find_device_by_ip(self, ip: str) -> Optional[Dict]:
        """按IP查找设备"""
        data = self._get(
            "/ne-mgr/v2/device/basic/query",
            params={"keyword": ip, "page": 0, "size": 10},
        )
        for item in data.get("items", []):
            if item.get("deviceIp") == ip:
                return item
        return None

    # ------------------------------------------------------------------
    # 拓扑
    # ------------------------------------------------------------------
    def get_topology(self, zone_id: int = 1) -> Dict:
        """获取拓扑（nodeList + linkList）"""
        return self._get(
            f"/topo-srv/v1/topology/Topo_pn:All:default/view",
            params={"zoneId": zone_id, "requireAttrFlag": 31, "recursion": True},
        )

    def get_port_list(self, device_id: str) -> List[Dict]:
        """获取设备端口列表"""
        data = self._get(
            "/ne-monitor/v1/analyzer-dcn/portCongestionInfos",
            params={"deviceId": device_id, "page": 0, "size": 200},
        )
        return data.get("content", [])

    # ------------------------------------------------------------------
    # 指标查询
    # ------------------------------------------------------------------
    def get_indicator_data(
        self,
        device_id: int,
        indicate_id: int,
        port: str = "-",
        slot: str = "Slot 0",
        start_time: int = None,
        end_time: int = None,
    ) -> List[Dict]:
        """查询单个指标时序数据"""
        now_ms = int(time.time() * 1000)
        body = {
            "device": device_id,
            "indicateId": indicate_id,
            "slot": slot,
            "port": port,
            "timeLimit": {
                "startTime": start_time or (now_ms - 3600_000),
                "endTime": end_time or now_ms,
            },
        }
        data = self._post(
            "/ne-monitor/v1/deviceIndicatorData/get-all-indicator-data",
            body,
        )
        return data.get("content", [])

    def get_indicators_batch(
        self,
        device_id: int,
        indicate_ids: List[int],
        port: str = "-",
        start_time: int = None,
        end_time: int = None,
    ) -> Dict[int, List[Dict]]:
        """批量查询多个指标，返回 {indicate_id: [数据点]}"""
        result = {}
        for iid in indicate_ids:
            try:
                result[iid] = self.get_indicator_data(
                    device_id, iid, port, start_time=start_time, end_time=end_time
                )
            except Exception:
                result[iid] = []
        return result

    # ------------------------------------------------------------------
    # 告警
    # ------------------------------------------------------------------
    def get_active_alerts(
        self,
        device_ip: str = None,
        start_time: int = None,
        end_time: int = None,
        page: int = 0,
        size: int = 100,
    ) -> List[Dict]:
        """查询活动告警"""
        body: Dict[str, Any] = {"status": "ACTIVE", "page": page, "size": size}
        if device_ip:
            body["deviceIp"] = device_ip
        if start_time:
            body["startTime"] = start_time
        if end_time:
            body["endTime"] = end_time
        data = self._post("/sys-monitor/v1/alert-records/alert-filter", body)
        return data.get("items", [])

    # ------------------------------------------------------------------
    # Syslog
    # ------------------------------------------------------------------
    def get_syslog(
        self,
        device_ip: str,
        keyword: str = None,
        level: str = "WARNINGS ERRORS CRITICAL ALERTS EMERGENCIES",
        start_time: int = None,
        end_time: int = None,
        page: int = 0,
        size: int = 100,
    ) -> List[Dict]:
        """查询设备Syslog"""
        now_ms = int(time.time() * 1000)
        conditions = [
            {"conditionType": "level", "conditionValue": level},
            {"conditionType": "deviceIp", "conditionValue": device_ip, "fuzzy": False},
        ]
        if keyword:
            conditions.append({"conditionType": "content", "conditionValue": keyword, "fuzzy": True})

        body = {
            "index": "devicesyslog",
            "andConditionList": conditions,
            "orConditionList": [],
            "startTime": start_time or (now_ms - 3600_000),
            "endTime": end_time or now_ms,
            "page": page,
            "size": size,
        }
        data = self._post("/sys-monitor/v1/device-logs", body)
        return data.get("items", [])

    # ------------------------------------------------------------------
    # 拥塞
    # ------------------------------------------------------------------
    def get_congestion_ports(
        self, zone_id: int = 1, start_time: int = None, end_time: int = None
    ) -> List[Dict]:
        """查询拥塞端口列表"""
        now_ms = int(time.time() * 1000)
        data = self._get(
            "/ne-monitor/v1/congestion/query",
            params={
                "zoneId": zone_id,
                "startTime": start_time or (now_ms - 3600_000),
                "endTime": end_time or now_ms,
                "page": 0,
                "size": 200,
            },
        )
        return data.get("congestion", [])
