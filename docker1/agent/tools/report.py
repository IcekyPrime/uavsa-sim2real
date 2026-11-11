"""评测报告生成：把会话历史汇总为 Markdown 报告，写入 results/。"""
from __future__ import annotations

import time
from pathlib import Path

from ..memory import Session


def _fmt_metrics(m: dict) -> str:
    if not m:
        return "（无）"
    rows = [f"- {k}: {v}" for k, v in m.items() if v is not None]
    return "\n".join(rows) if rows else "（无）"


def generate_report(session: Session, results_dir: Path) -> dict:
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    fname = f"report-{session.id}-{ts}.md"
    path = results_dir / fname

    lines = [
        f"# UAVSA 评测报告",
        "",
        f"- 会话 ID：`{session.id}`",
        f"- 任务目标：{session.goal}",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 迭代轮次：{len(session.metrics_history)}",
        f"- 补丁次数：{len(session.patch_history)}",
        "",
        "## 指标变化历史",
        "",
    ]
    if session.metrics_history:
        lines.append("| 轮次 | 飞行态 | 跟踪误差(巡航) | 收敛时间 | 到达航点 | 碰撞 | 安全告警 | 平滑度 | 异常分 |")
        lines.append("|------|--------|----------------|----------|----------|------|----------|--------|--------|")
        for i, m in enumerate(session.metrics_history, 1):
            reached = m.get("_reached_waypoints")
            total = m.get("_total_waypoints")
            wp = f"{reached}/{total}" if reached is not None and total else "-"
            lines.append(
                f"| {i} | {m.get('_flight_state', '-')} | {m.get('tracking_error_m')} "
                f"| {m.get('convergence_time_s')} | {wp} "
                f"| {m.get('collision_count')} | {m.get('safety_violations')} "
                f"| {m.get('smoothness')} | {m.get('anomaly_score')} |"
            )
        lines += ["", "> 主指标只统计 `cruise` 相位；到达航点仅统计采样窗口内，窗口较短时不必覆盖全部航点。"]
    else:
        lines.append("（无指标记录）")

    # 分相位指标：同相位之间才可比较
    phase_rows = [m for m in session.metrics_history if m.get("_phase_summary")]
    if phase_rows:
        lines += ["", "## 分相位指标（同相位可比）", ""]
        lines.append("| 轮次 | 相位 | 采样数 | 时长(s) | 跟踪误差 | 最大误差 | 平均速度 | 加速度RMS |")
        lines.append("|------|------|--------|---------|----------|----------|----------|-----------|")
        for i, m in enumerate(session.metrics_history, 1):
            for ph, s in (m.get("_phase_summary") or {}).items():
                lines.append(
                    f"| {i} | {ph} | {s.get('samples')} | {s.get('duration_s')} "
                    f"| {s.get('tracking_error_m')} | {s.get('max_error_m')} "
                    f"| {s.get('mean_speed')} | {s.get('accel_rms')} |"
                )
        lines += ["", "> 主指标只在 `cruise` 相位统计；`hover` 段的低误差不代表跟踪性能更好。"]

    lines += ["", "## 纠偏补丁", ""]
    if session.patch_history:
        for i, p in enumerate(session.patch_history, 1):
            lines.append(f"### 补丁 {i}")
            lines.append(f"- 说明：{p.get('message', '')}")
            changes = p.get("changes") or []
            if changes:
                for ch in changes:
                    if ch.get("params"):
                        kv = ", ".join(f"`{k}={v}`" for k, v in ch["params"].items())
                        lines.append(f"- 参数：`{ch.get('path')}` ← {kv}")
                    else:
                        lines.append(f"- 文件：`{ch.get('path')}`（整文件覆盖）")
            else:
                for f in p.get("files", []):
                    lines.append(f"- 修改文件：`{f}`")
            lines.append("")
    else:
        lines.append("（无补丁）")

    lines += ["", "## 执行步骤", ""]
    for s in session.steps:
        lines.append(f"- **[{s.role}]** {s.content[:200]}")

    path.write_text("\n".join(lines), encoding="utf-8")
    return {"path": str(path), "filename": fname}
