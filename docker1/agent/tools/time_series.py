"""时序判别器（v1.0 规则 + 轻量统计；预留训练模型加载接口）。

对应 Plan.md 的「时序自回归判别器」设想：对轨迹 / 指标时序做质量与异常判别。
v1.0 先实现可复用的统计判别（均值、离散度、突变/尖峰检测），并暴露模型插槽，
后续可加载训练好的判别器替换。
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np


def _zscore_spikes(series: list[float], threshold: float = 3.0) -> int:
    if len(series) < 4:
        return 0
    arr = np.asarray(series, dtype=float)
    mean, std = float(arr.mean()), float(arr.std())
    if std == 0:
        return 0
    z = np.abs((arr - mean) / std)
    return int((z > threshold).sum())


class TimeSeriesAnalyzer:
    """可插拔时序判别器。`model_path` 指向训练好的判别器（v1.0 忽略，预留）。"""

    def __init__(self, model_path: str | None = None):
        self.model_path = model_path

    def analyze_series(self, series: list[float], name: str = "series") -> dict:
        if not series:
            return {"name": name, "error": "空序列"}
        arr = np.asarray(series, dtype=float)
        mean = float(arr.mean())
        std = float(arr.std())
        rms = float(np.sqrt(np.mean(arr ** 2)))
        spikes = _zscore_spikes(series)
        # 异常分：归一化离散度 + 尖峰惩罚
        anomaly = min(1.0, (std / (abs(mean) + 1e-6)) * 0.5 + spikes * 0.15)
        return {
            "name": name,
            "length": len(series),
            "mean": round(mean, 4),
            "std": round(std, 4),
            "rms": round(rms, 4),
            "min": round(float(arr.min()), 4),
            "max": round(float(arr.max()), 4),
            "spike_count": spikes,
            "anomaly_score": round(min(1.0, anomaly), 4),
            "verdict": "异常偏高" if anomaly > 0.6 else ("略需关注" if anomaly > 0.3 else "正常"),
        }

    def analyze_metrics(self, metrics: dict) -> dict:
        """对一次运行的标准化指标做质量判别。"""
        if not metrics:
            return {"error": "无指标"}
        notes = []
        anomaly = metrics.get("anomaly_score", 0.0) or 0.0
        if metrics.get("collision_count", 0):
            notes.append(f"发生 {metrics['collision_count']} 次碰撞")
        if metrics.get("safety_violations", 0):
            notes.append(f"存在 {metrics['safety_violations']} 次安全约束违反")
        if metrics.get("smoothness", 0) is not None and metrics.get("smoothness", 0) > 0.6:
            notes.append("平滑度偏高，轨迹可能存在抖振")
        if metrics.get("tracking_error_m", 0) is not None and metrics.get("tracking_error_m", 0) > 0.3:
            notes.append("跟踪误差偏大")
        if metrics.get("_flight_state") == "hover":
            notes.append("采样窗口内无巡航段，主指标不可用于跨轮比较")
        return {
            "anomaly_score": anomaly,
            "issues": notes,
            "verdict": "存在明显异常" if notes or anomaly > 0.6 else "运行基本正常",
        }

    # ---- 轨迹时序判别（v1.1） ----
    _FIELD_ALIAS = {
        "tracking_error_m": "err", "tracking_error": "err", "error": "err",
        "speed": "speed", "velocity": "speed",
        "smoothness": "accel", "acceleration": "accel", "accel": "accel",
        "x": "x", "y": "y", "z": "z",
    }

    def _extract(self, rows: list[dict], field: str) -> list[float]:
        """从轨迹 rows 中抽取指定字段的数值序列。"""
        if field == "speed":
            return [math.sqrt(r["vx"] ** 2 + r["vy"] ** 2 + r["vz"] ** 2)
                    for r in rows if r.get("vx") is not None]
        if field == "accel":
            out = []
            for a, b in zip(rows, rows[1:]):
                dt = b["t"] - a["t"]
                if dt <= 0:
                    continue
                dvx, dvy, dvz = b["vx"] - a["vx"], b["vy"] - a["vy"], b["vz"] - a["vz"]
                out.append(math.sqrt(dvx * dvx + dvy * dvy + dvz * dvz) / dt)
            return out
        return [float(r[field]) for r in rows if r.get(field) is not None]

    def analyze_trajectory(self, rows: list[dict], field: str = "err") -> dict:
        """对单次飞行的真实时序做分相位判别（而非跨轮标量）。"""
        if not rows:
            return {"error": "无轨迹时序，请先调用 run_algorithm"}
        field = self._FIELD_ALIAS.get(field or "err", field or "err")
        if field not in ("err", "speed", "accel", "x", "y", "z"):
            return {"error": f"不支持的字段 {field}；可用 err/speed/accel/x/y/z"}

        overall = self.analyze_series(self._extract(rows, field), field)
        by_phase = {}
        for ph in ("takeoff", "cruise", "hover"):
            sub = [r for r in rows if r.get("phase") == ph]
            if sub:
                by_phase[ph] = self.analyze_series(self._extract(sub, field), ph)

        note = ""
        if "cruise" in by_phase and "hover" in by_phase:
            c = by_phase["cruise"].get("mean")
            h = by_phase["hover"].get("mean")
            if c is not None and h is not None:
                note = f"巡航段均值 {c}、悬停段均值 {h}；两者物理含义不同，不可跨相位直接比较。"

        verdict = overall.get("verdict", "")
        if "cruise" in by_phase:
            verdict = by_phase["cruise"].get("verdict", verdict)

        return {
            "field": field,
            "samples": len(rows),
            "overall": overall,
            "by_phase": by_phase,
            "phase_note": note,
            "verdict": verdict,
        }
