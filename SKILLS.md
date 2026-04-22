# ShowShow Skills

ShowShow 是面向GPU算力集群的端网协同故障诊断CLI工具。
输入问题节点，输出根因定位。

---

## 工具能力概览

```
showshow diagnose  —— 端到端故障诊断（路径+指标+根因）
showshow path      —— 单独查看AILB路径
showshow inspect   —— 预防性巡检
```

---

## 场景一：训练中断 / 训练慢

**触发条件**：用户说训练挂了、中断、abort、慢了、性能下降

**执行步骤**：
```bash
# 基础诊断
showshow diagnose --src <nodeA_ip> --dst <nodeB_ip>

# 带时间点（推荐，更精准）
showshow diagnose --src <nodeA_ip> --dst <nodeB_ip> --time "YYYY-MM-DD HH:MM"

# 含PCIe拓扑（高级模式，排查端侧问题）
showshow diagnose --src <nodeA_ip> --dst <nodeB_ip> --pcie
```

**输出解读**：
- `El Culpable 根因定位` 面板：列出异常节点和具体原因
- 路径图：显示 GPU→NIC→Leaf→Spine→Leaf→NIC→GPU 完整链路
- 指标表：每跳的PFC/ECN/丢包/Headroom
- 若网络正常：建议检查主机侧配置

**异常判定逻辑**：
- PFC发送/接收速率 > 100pps → PFC反压异常
- ECN标记速率 > 1000pps → 拥塞
- TX/RX丢包 > 0 → 有丢包
- Headroom占用率 > 80% → Buffer压力大
- NAK > 0 → RDMA重传

---

## 场景二：路径查询

**触发条件**：用户想知道两个节点之间走的哪条路

```bash
showshow path --src <nodeA_ip> --dst <nodeB_ip>
```

**输出**：完整AILB路径 + member-id计算结果

---

## 场景三：集群巡检

**触发条件**：部署前检查、定期体检、发现奇怪问题先跑巡检

```bash
# 全量巡检
showshow inspect

# 只查指定节点主机侧
showshow inspect --nodes 10.159.161.1,10.159.161.2 --scope host

# 只查网络侧
showshow inspect --scope network
```

**检查项**：
- 主机侧：CPU高性能模式、iommu关闭、nouveau禁用、ECC跳变、PCIe降速
- 网络侧：PFC告警、拥塞告警

---

## 参数说明

| 参数 | 说明 | 示例 |
|---|---|---|
| `--src` | 源GPU服务器IP | `10.159.161.1` |
| `--dst` | 目的GPU服务器IP | `10.159.161.8` |
| `--time` | 故障时间点 | `"2024-01-10 14:00"` |
| `--pcie` | 包含PCIe拓扑分析 | 无参数值 |
| `--no-cache` | 强制刷新设备配置 | 无参数值 |
| `--zone` | ONC区域ID | `1` |
| `--scope` | 巡检范围 | `host/network/all` |
| `--nodes` | 指定巡检节点 | `10.x.x.1,10.x.x.2` |

---

## 配置文件

位置：`~/.showshow/config.yaml`

```yaml
onc:
  host: 172.28.200.80
  port: 18080

ssh:
  default_user: root
  default_password: ""

network:
  roce_priority: 3      # RoCE流量Priority，P3或P4
  config_cache_ttl: 300 # 设备配置缓存TTL（秒）
```

---

## 典型对话示例

用户：node01和node08之间训练挂了
Agent：`showshow diagnose --src <node01_ip> --dst <node08_ip>`

用户：昨天下午两点训练慢了
Agent：`showshow diagnose --src <ip> --dst <ip> --time "2024-01-10 14:00"`

用户：帮我看看node03的PCIe有没有问题
Agent：`showshow diagnose --src <node03_ip> --dst <any_ip> --pcie`
或：`showshow inspect --nodes <node03_ip> --scope host`

用户：全集群巡检一下
Agent：`showshow inspect`
