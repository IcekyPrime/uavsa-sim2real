"""sim_bridge 与 agent 之间约定的标准化评测指标。

统一指标命名，保证「真实仿真」与「Mock 演示」产出的指标结构一致，
便于 agent 的 `read_metrics` 工具与后续报告生成直接复用。
"""

# 标准指标键名（所有后端必须产出）
METRIC_KEYS = [
    "tracking_error_m",   # 轨迹跟踪误差（m），越低越好
    "convergence_time_s", # 收敛时间（s），越低越好
    "success_rate",       # 成功率 [0,1]，越高越好
    "collision_count",    # 碰撞次数，越低越好
    "overshoot",          # 超调量，越低越好
    "smoothness",         # 平滑度（jerk RMS 等），越低越好
    "energy",             # 能耗（归一化），越低越好
    "safety_violations",  # 安全约束违反次数，越低越好
    "anomaly_score",      # 时序判别器异常分 [0,1]，越低越好
]

# 每个指标是否为「越低越好」；用于报告里判断趋势
LOWER_IS_BETTER = {
    "tracking_error_m": True,
    "convergence_time_s": True,
    "success_rate": False,
    "collision_count": True,
    "overshoot": True,
    "smoothness": True,
    "energy": True,
    "safety_violations": True,
    "anomaly_score": True,
}


def aggregate(runs: list[dict]) -> dict:
    """对多次运行得到的指标列表求平均（success_rate 同样取均值）。"""
    if not runs:
        return {k: None for k in METRIC_KEYS}
    agg = {}
    for k in METRIC_KEYS:
        vals = [r.get(k) for r in runs if isinstance(r.get(k), (int, float))]
        agg[k] = round(sum(vals) / len(vals), 6) if vals else None
    return agg
