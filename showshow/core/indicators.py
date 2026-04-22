"""ShowShow ONC指标ID常量"""

# ============================================================
# PORT级别指标 (objectType=PORT)
# ============================================================
PORT = {
    # 流量
    "rx_pkts":       2038,
    "tx_pkts":       2039,
    "rx_drop_pkts":  2040,
    "tx_drop_pkts":  2041,
    "rx_error_pkts": 2042,
    "tx_error_pkts": 2043,
    "rx_bytes":      2046,
    "tx_bytes":      2047,
    "rx_bw_usage":   2052,  # %
    "tx_bw_usage":   2053,  # %
    "rx_rate_bps":   2317,
    "tx_rate_bps":   2318,
    "rx_rate_pps":   2319,
    "tx_rate_pps":   2320,
    "crc_error":     2300,
    # ECN/WRED
    "wred_drop":     2037,
    "ecn_marked":    2291,
    "ecn_rate":      2555,
    # RDMA NAK/CNP (交换机端口级别)
    "nak_tx":        2385,
    "nak_rx":        2386,
    "cnp_tx":        2387,
    "cnp_rx":        2388,
    "nak_tx_rate":   2573,
    "nak_rx_rate":   2574,
    "cnp_tx_rate":   2591,
    "cnp_rx_rate":   2592,
    # Buffer
    "headroom_used": 2062,  # %
}

# ============================================================
# QUEUE级别指标 (objectType=QUEUE)
# PFC per-priority: priority 0-7 对应 offset 0-7
# ============================================================
QUEUE = {
    # PFC发送帧数 per-priority (2337=P0, 2338=P1, ..., 2344=P7)
    "pfc_send":      {i: 2337 + i for i in range(8)},
    # PFC接收帧数 per-priority
    "pfc_recv":      {i: 2345 + i for i in range(8)},
    # PFC发送速率 per-priority
    "pfc_send_rate": {i: 2396 + i for i in range(8)},
    # PFC接收速率 per-priority
    "pfc_recv_rate": {i: 2404 + i for i in range(8)},
    # PFC汇总
    "pfc_recv_total":      2551,
    "pfc_send_total":      2552,
    "pfc_send_rate_total": 2553,
    "pfc_recv_rate_total": 2554,
    # MMU单播队列丢包 per-queue (2003=Q0, ..., 2010=Q7)
    "unicast_drop_pkts":  {i: 2003 + i for i in range(8)},
    "unicast_drop_bytes": {i: 2011 + i for i in range(8)},
    # MMU多播队列丢包 per-queue
    "mcast_drop_pkts":    {i: 2019 + i for i in range(8)},
    "mcast_drop_bytes":   {i: 2027 + i for i in range(8)},
}

# ============================================================
# NIC级别指标 (objectType=NIC) - 服务器网卡
# ============================================================
NIC = {
    "tx_drop":           2450,
    "rx_drop":           2451,
    "tx_max_speed":      2452,
    "rx_max_speed":      2453,
    "tx_min_speed":      2454,
    "rx_min_speed":      2455,
    "rx_pfc":            2456,  # 接收PFC数
    "tx_pfc":            2457,  # 发送PFC数
    "rx_cnp":            2458,
    "tx_cnp":            2459,
    "ecn_marked":        2460,
    "rnr_nak":           2461,  # RNR NAK
    "nak_seq_err":       2471,
    "out_of_buffer":     2472,  # 接收缓存不足丢包
    "out_of_sequence":   2473,
    "tx_errors":         2550,
    "ecn_marked_rate":   2556,
    "rx_cnp_rate":       2593,
    "tx_cnp_rate":       2594,
    "rnr_nak_rate":      2595,
    "nak_seq_err_rate":  2596,
    "rx_pfc_rate":       2606,
    "tx_pfc_rate":       2607,
    "tx_avg_speed":      2608,
    "rx_avg_speed":      2609,
    "tx_bw_usage":       2637,  # %
    "rx_bw_usage":       2638,  # %
    "tx_pps":            2675,
    "rx_pps":            2676,
}

# ============================================================
# NIC_QUEUE级别指标 (objectType=NIC_QUEUE) - 网卡队列
# Queue编号1-8对应Priority 0-7
# ============================================================
NIC_QUEUE = {
    # 接收/发送字节数 per-queue
    "rx_bytes":    {i: 2474 + i for i in range(8)},   # Queue1-8
    "tx_bytes":    {i: 2482 + i for i in range(8)},
    # 接收/发送包数 per-queue
    "rx_pkts":     {i: 2490 + i for i in range(8)},
    "tx_pkts":     {i: 2498 + i for i in range(8)},
    # PFC pause帧 per-queue
    "rx_pause":    {i: 2506 + i for i in range(8)},
    "tx_pause":    {i: 2514 + i for i in range(8)},
    # 丢包 per-queue
    "rx_buf_discard":  {i: 2522 + i for i in range(8)},  # 缓存不足丢包
    "rx_cong_discard": {i: 2530 + i for i in range(8)},  # 拥塞丢包
    # ECN标记 per-queue
    "ecn_marked":      {i: 2538 + i for i in range(8)},
    "ecn_marked_rate": {i: 2597 + i for i in range(8)},
    # 速率 per-queue
    "tx_speed":    {i: 2677 + i for i in range(8)},
    "rx_speed":    {i: 2685 + i for i in range(8)},
    "tx_pps":      {i: 2693 + i for i in range(8)},
    "rx_pps":      {i: 2701 + i for i in range(8)},
}

# ============================================================
# GPU级别指标 (objectType=GPU)
# ============================================================
GPU = {
    "power":       2462,  # 功耗
    "gpu_usage":   2463,  # GPU使用率 %
    "mem_usage":   2464,  # 显存使用率 %
    "temp":        2465,  # 温度
    "tx_clock":    2466,
    "sm_clock":    2467,
    "nc_clock":    2468,
    "sp_clock":    2469,
}

# ============================================================
# ShowShow核心关注的指标集合（按场景）
# ============================================================

# 拥塞判定必查指标
CONGESTION_INDICATORS = {
    "switch_port": [
        PORT["ecn_marked"],
        PORT["wred_drop"],
        PORT["tx_drop_pkts"],
        PORT["rx_drop_pkts"],
        PORT["headroom_used"],
    ],
    "switch_queue_pfc": lambda p: [
        QUEUE["pfc_send"][p],
        QUEUE["pfc_recv"][p],
        QUEUE["pfc_send_rate"][p],
        QUEUE["pfc_recv_rate"][p],
        QUEUE["unicast_drop_pkts"][p],
    ],
    "nic": [
        NIC["rx_pfc"],
        NIC["tx_pfc"],
        NIC["rx_cnp"],
        NIC["tx_cnp"],
        NIC["ecn_marked"],
        NIC["out_of_buffer"],
        NIC["rx_drop"],
        NIC["tx_drop"],
    ],
    "nic_queue_pfc": lambda p: [
        NIC_QUEUE["rx_pause"][p],
        NIC_QUEUE["tx_pause"][p],
        NIC_QUEUE["rx_cong_discard"][p],
        NIC_QUEUE["ecn_marked"][p],
    ],
}
