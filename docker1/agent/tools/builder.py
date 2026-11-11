"""工具构建器：把后端 / 知识库 / 会话绑定为可供 Agent 调用的工具集。"""
from __future__ import annotations

from ..backends.base import AlgoBackend, SimBackend
from ..config import Config
from ..memory import Session
from .knowledge import KnowledgeBase
from .registry import Tool, ToolRegistry, safe_json
from .report import generate_report
from .time_series import TimeSeriesAnalyzer


def build_tools(
    sim: SimBackend,
    algo: AlgoBackend,
    session: Session,
    config: Config,
    knowledge: KnowledgeBase,
    analyzer: TimeSeriesAnalyzer,
) -> ToolRegistry:
    registry = ToolRegistry()

    # 1. 知识检索
    registry.register(Tool(
        name="search_algorithm",
        description="在知识库中检索同类算法、调参经验与常见故障案例，用于理解问题背景。",
        parameters={"query": {"type": "string", "description": "检索关键词或问题描述", "required": True}},
        tags=["检索"],
        func=lambda a: _search(knowledge, a.get("query", ""), 5),
    ))
    registry.register(Tool(
        name="retrieve_knowledge",
        description="RAG 检索：返回知识库中最相关的文本片段，供分析与引用；未命中时返回可检索的文档目录。",
        parameters={
            "query": {"type": "string", "description": "查询语句", "required": True},
            "top_k": {"type": "integer", "description": "返回条数", "required": False},
        },
        tags=["检索"],
        func=lambda a: _search(knowledge, a.get("query", ""), int(a.get("top_k", 5))),
    ))

    # 2. 仿真控制
    registry.register(Tool(
        name="run_simulation",
        description="启动仿真场景（Gazebo/PX4），可设置障碍物密度与风场。",
        parameters={
            "obstacle_density": {"type": "number", "description": "障碍物密度 0~1", "required": False},
            "wind_m_s": {"type": "number", "description": "风速 m/s", "required": False},
        },
        tags=["仿真"],
        func=lambda a: sim.start_scenario({
            "obstacle_density": float(a.get("obstacle_density", 0.5)),
            "wind_m_s": float(a.get("wind_m_s", 0.0)),
        }),
    ))
    registry.register(Tool(
        name="stop_simulation",
        description="停止当前仿真场景。",
        parameters={},
        tags=["仿真"],
        func=lambda a: sim.stop(),
    ))
    registry.register(Tool(
        name="read_metrics",
        description="读取当前运行的标准化评测指标（跟踪误差、收敛时间、成功率、碰撞、平滑度、异常分等）。",
        parameters={},
        tags=["评测"],
        func=lambda a: _read_metrics(sim, session, analyzer),
    ))

    # 3. 算法控制
    registry.register(Tool(
        name="build_algorithm",
        description="编译 docker2 上的被测算法。",
        parameters={},
        tags=["算法"],
        func=lambda a: algo.build(),
    ))
    registry.register(Tool(
        name="run_algorithm",
        description="运行被测算法并返回真实飞行时序（10Hz：t/位置/速度/指令/跟踪误差/飞行相位）与本次指标。",
        parameters={"duration_s": {"type": "number", "description": "采样时长（秒），3~15，默认 12", "required": False}},
        tags=["算法"],
        func=lambda a: _run_algo(session, algo, float(a.get("duration_s", 12.0))),
    ))
    registry.register(Tool(
        name="patch_algorithm",
        description="把代码/参数补丁应用到被测算法（自动备份原文件）。files 每项二选一："
                    "整文件覆盖 {path, content}；或参数覆盖 {path, params:{参数名:新值}}（推荐用于 XML 调参，如 advanced_param_px4.xml）。",
        parameters={
            "files": {"type": "array", "description": "补丁文件列表，每项含 path+content 或 path+params", "required": True},
            "message": {"type": "string", "description": "补丁说明", "required": False},
        },
        tags=["算法"],
        func=lambda a: _patch(session, algo, a),
    ))

    # 4. 时序判别
    registry.register(Tool(
        name="analyze_time_series",
        description="对最近一次真实飞行时序做分相位判别（巡航/悬停分别统计，支持 err/speed/accel/x/y/z）。",
        parameters={"metric_name": {"type": "string", "description": "要分析的字段，默认 err（跟踪误差）", "required": False}},
        tags=["评测"],
        func=lambda a: _analyze_ts(session, analyzer, a.get("metric_name")),
    ))

    # 5. 报告
    registry.register(Tool(
        name="generate_report",
        description="汇总本次任务历次迭代，生成 Markdown 评测报告并保存。",
        parameters={},
        tags=["报告"],
        func=lambda a: generate_report(session, config.results_dir),
    ))

    return registry


# ---- 工具内部实现 ----
def _search(knowledge: KnowledgeBase, query: str, top_k: int) -> dict:
    """检索并给出未命中引导，避免低分噪声或空结果让模型瞎猜。"""
    results = knowledge.retrieve(query, top_k)
    if results:
        return {"results": results}
    return {
        "results": [],
        "note": "知识库未命中。请换用更具体的术语（参数名如 optimization/lambda_smooth、"
                "指标名如 tracking_error_m、飞行态如 hover/WAIT_TARGET、工具名如 run_algorithm）。",
        "available_docs": knowledge.titles(),
    }


def _read_metrics(sim: SimBackend, session: Session, analyzer: TimeSeriesAnalyzer) -> dict:
    m = sim.metrics()
    series = m.pop("_series", None)
    if series:
        session.add_trajectory("metrics", series)
    session.add_metrics(m)
    diag = analyzer.analyze_metrics(m)
    return {"metrics": m, "diagnosis": diag}


def _run_algo(session: Session, algo: AlgoBackend, duration_s: float) -> dict:
    """运行算法：完整时序存入会话，返回体只带降采样轨迹，避免撑爆 LLM 上下文。"""
    result = algo.run(duration_s)
    series = result.pop("_series", None)
    if series:
        session.add_trajectory("run_algorithm", series)
    # run_algorithm 已附带本次指标，登记进历史，保证报告覆盖每一轮
    m = result.get("metrics")
    if isinstance(m, dict) and m:
        m = dict(m)
        m["_phase_summary"] = result.get("phase_summary") or {}
        m["_flight_state"] = result.get("flight_state")
        m["_waypoints"] = result.get("waypoints") or []
        m["_reached_waypoints"] = result.get("reached_waypoints")
        m["_total_waypoints"] = result.get("total_waypoints")
        session.add_metrics(m)
    return result


def _patch(session: Session, algo: AlgoBackend, args: dict) -> dict:
    files = args.get("files", [])
    message = args.get("message", "")
    result = algo.patch(files, message)
    # 记录具体改动，供报告与知识库案例沉淀使用
    changes = []
    for f in files:
        path = f.get("path", "")
        if isinstance(f.get("params"), dict) and f["params"]:
            changes.append({"path": path, "params": dict(f["params"])})
        elif f.get("content"):
            changes.append({"path": path, "content_chars": len(f["content"])})
    session.add_patch({
        "files": [f.get("path") for f in files],
        "message": message,
        "changes": changes,
        "status": result.get("status") if isinstance(result, dict) else None,
    })
    return result


def _analyze_ts(session: Session, analyzer: TimeSeriesAnalyzer, metric_name: str | None) -> dict:
    # 优先分析最近一次真实飞行时序（单次运行内的时间轴）
    if session.last_trajectory:
        return analyzer.analyze_trajectory(session.last_trajectory, metric_name or "err")

    # 回退：仅有历次聚合指标时，跨轮比较（样本稀疏，仅供参考）
    if not session.metrics_history:
        return {"error": "尚无轨迹或指标历史，请先运行 run_algorithm / read_metrics"}
    name = metric_name or "tracking_error_m"
    series = [m.get(name) for m in session.metrics_history if m.get(name) is not None]
    if not series:
        last = session.metrics_history[-1]
        series = [last.get("smoothness"), last.get("overshoot"), last.get("anomaly_score")]
        series = [x for x in series if x is not None]
        name = "composite"
    out = analyzer.analyze_series(series, name)
    out["note"] = "当前只有历次聚合指标（每轮 1 个样本），趋势判断置信度低；run_algorithm 后可获得真实时序。"
    return out
