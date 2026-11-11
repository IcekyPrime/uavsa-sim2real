"""Agent 自适应纠偏循环（ReAct）。

- 有 LLM：按「检索→封装→仿真→评测→分析→补丁→重跑」闭环自主纠偏。
- 无 LLM / 调用失败：回退到确定性基线循环（跑一轮 + 报告），保证平台可运行。
"""
from __future__ import annotations

from typing import Callable

from .config import Config
from .llm import LLMClient, llm as default_llm
from .memory import Session
from .tools.builder import build_tools
from .tools.knowledge import KnowledgeBase, append_case
from .tools.registry import ToolRegistry, safe_json
from .tools.time_series import TimeSeriesAnalyzer

ProgressFn = Callable[[dict], None]


def _noop(event: dict):
    pass


SYSTEM_PROMPT = """你是 UAVSA-v1.0 平台的无人机算法纠偏 Agent。
你的目标：让用户给出的无人机算法在仿真中达到更好指标，缩小仿真到实机的差异。
你通过调用工具完成「检索 → 封装 → 仿真 → 评测 → 分析 → 补丁 → 重跑」的闭环。

可用工具（调用时输出 JSON）：
{tool_specs}

输出格式（每次只输出一个 JSON 对象，不要夹杂其它文字）：
- 调用工具：{{"thought": "<用一两句话说明你此刻的判断与理由>", "action": "<工具名>", "input": {{<参数>}}}}
- 最终回答：{{"thought": "<简短总结你的判断>", "answer": "<给用户的总结>", "patch_summary": "<补丁要点>"}}

规则：
1. 先 read_metrics / analyze_time_series 分析现状，再决定是否 patch。
2. patch_algorithm 的 files 每项含 path（相对路径）与 content（完整新内容）。
3. 最多 {max_iterations} 轮补丁，收敛（成功率趋近 1 且异常分低）后调用 generate_report 并输出 answer。
4. 分析结论必须锚定工具输出，不要凭空猜测。
5. 观测数据带飞行相位（takeoff/cruise/hover）：tracking_error/smoothness 等主指标只在 cruise 相位统计；
   hover 段误差低只是因为无人机停着，不能当作优化收益。改前/改后必须在同一相位下比较。
6. run_algorithm 返回的是 10Hz 真实时序（t/x/y/z/vx/vy/vz/cmd/err/phase），可先用 analyze_time_series 定位问题段。
7. 若 flight_state 为 hover 或轨迹位移≈0，先判断是「已到终点悬停」还是「没有生成轨迹」，不要盲目调参。
8. 决定改哪个参数前先 retrieve_knowledge 查参数地图，确认该参数真正生效；不要改任务结构参数
   （fsm/waypoint*、fsm/flight_type）或无效参数（bspline/limit_*）。"""

USER_PROMPT = """任务目标：{goal}
用户提供的算法：{algorithm}

建议流程：
1. search_algorithm 或 retrieve_knowledge 了解算法与调参要点；
2. build_algorithm 编译；
3. run_simulation 启动仿真；
4. run_algorithm 运行算法；
5. read_metrics 读取指标；
6. analyze_time_series 判别时序质量；
7. 结合指标与知识生成补丁 patch_algorithm；
8. build_algorithm 重新编译 → 回到第 4 步；
9. 收敛后 generate_report 并输出 answer。
请开始。"""


class Agent:
    def __init__(
        self,
        sim,
        algo,
        config: Config | None = None,
        llm_client: LLMClient | None = None,
    ):
        self.sim = sim
        self.algo = algo
        self.config = config or Config()
        self.llm = llm_client or default_llm
        self.knowledge = KnowledgeBase(self.config.knowledge_dir)
        self.analyzer = TimeSeriesAnalyzer()
        self._iter = 0

    # ---- 公共入口 ----
    def run(self, goal: str, algorithm: str = "", progress: ProgressFn | None = None) -> dict:
        emit = progress or _noop
        session = Session(goal)
        self._iter = 0
        emit({"type": "start", "session_id": session.id, "goal": goal, "backend": type(self.sim).__name__})

        registry = build_tools(self.sim, self.algo, session, self.config, self.knowledge, self.analyzer)

        try:
            # 无 API Key 时走确定性基线（以 llm 客户端实际持有的 key 为准）
            if not self.llm.api_key:
                emit({"type": "log", "content": "未配置 LLM_API_KEY，回退到确定性基线循环（仅演示闭环，不产生真实纠偏）"})
                return self._baseline_loop(session, registry, emit)

            try:
                return self._react_loop(session, registry, goal, algorithm, emit)
            except Exception as e:
                emit({"type": "log", "content": f"LLM 循环异常：{e}，回退基线循环"})
                return self._baseline_loop(session, registry, emit)
        finally:
            # 无论成功/失败/无 Key，都把可复用的「症状-补丁-结果」沉淀进知识库
            self._persist_case(session, emit)

    def _persist_case(self, session: Session, emit: ProgressFn):
        try:
            path = append_case(self.config.knowledge_dir, session)
            if path:
                self.knowledge.rebuild_index()
                emit({"type": "log", "content": f"已沉淀故障案例：knowledge/cases/{path.name}"})
        except Exception as e:
            emit({"type": "log", "content": f"案例沉淀跳过：{type(e).__name__}: {e}"})

    # ---- ReAct 循环 ----
    def _react_loop(self, session, registry, goal, algorithm, emit) -> dict:
        system = SYSTEM_PROMPT.format(
            tool_specs=registry.spec_text(),
            max_iterations=self.config.llm_max_iterations,
        )
        user = USER_PROMPT.format(goal=goal, algorithm=algorithm or "（未指定，默认 EGO-Planner）")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

        max_steps = max(6, self.config.llm_max_iterations * 4)
        for step in range(max_steps):
            reasoning, text = self.llm.chat_full(messages)
            parsed = LLMClient.extract_json(text)

            thought = reasoning or (parsed.get("thought") if parsed else "")
            if thought:
                emit({"type": "thought", "content": thought})
                session.add("thought", thought)

            if parsed and "answer" in parsed:
                emit({"type": "final", "content": parsed.get("answer", ""), "patch_summary": parsed.get("patch_summary", "")})
                session.add("final", parsed.get("answer", ""))
                return session.to_report()

            if parsed and "action" in parsed:
                action = parsed["action"]
                args = parsed.get("input") or {}
                emit({"type": "action", "tool": action, "input": args})
                session.add("action", f"调用 {action}({safe_json(args)})")
                result = registry.execute(action, args)
                emit({"type": "observation", "tool": action, "result": result})
                session.add("observation", safe_json(result))
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": f"工具 {action} 返回：{safe_json(result)}"})
                continue

            # 既非 action 也非 answer：当作说明，请其继续
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": "请继续，按约定输出 JSON（action 或 answer）。"})

        emit({"type": "final", "content": "达到最大步数，流程结束。", "patch_summary": ""})
        return session.to_report()

    # ---- 确定性基线循环 ----
    def _baseline_loop(self, session, registry, emit) -> dict:
        steps = [
            ("build_algorithm", {}, "先编译被测算法，确保代码可运行，为后续仿真做准备。"),
            ("run_simulation", {"obstacle_density": 0.5}, "启动中等障碍密度的仿真场景，复现算法真实运行环境。"),
            ("run_algorithm", {"duration_s": 5.0}, "运行算法 5 秒，采集规划轨迹作为评测输入。"),
            ("read_metrics", {}, "读取标准化指标，量化当前表现，建立纠偏基线。"),
            ("analyze_time_series", {}, "对指标时序做异常判别，判断是否需要进行补丁纠偏。"),
        ]
        for name, args, thought in steps:
            emit({"type": "thought", "content": thought})
            session.add("thought", thought)
            emit({"type": "action", "tool": name, "input": args})
            r = registry.execute(name, args)
            emit({"type": "observation", "tool": name, "result": r})
            session.add("action", f"调用 {name}")
            session.add("observation", safe_json(r))

        # 演示一次补丁机制（仅基线模式占位，真实纠偏需 LLM）
        emit({"type": "thought", "content": "诊断显示指标仍有改善空间，生成参数补丁并应用，随后重跑以验证收敛。"})
        session.add("thought", "诊断显示指标仍有改善空间，生成参数补丁并应用。")
        demo_patch = {
            "files": [{
                "path": "baseline_demo.xml",
                "content": '<?xml version="1.0"?>\n<config>\n  <w_smooth>1.2</w_smooth>\n</config>\n',
            }],
            "message": "基线演示补丁（真实纠偏需配置 LLM_API_KEY）",
        }
        emit({"type": "action", "tool": "patch_algorithm", "input": demo_patch})
        r = registry.execute("patch_algorithm", demo_patch)
        emit({"type": "observation", "tool": "patch_algorithm", "result": r})

        emit({"type": "thought", "content": "迭代已收敛，汇总历次指标与补丁，生成评测报告并结束。"})
        session.add("thought", "迭代已收敛，汇总并生成报告。")
        rep = registry.execute("generate_report", {})
        emit({"type": "final", "content": "基线循环完成，报告已生成（配置 LLM_API_KEY 后可获得真实的纠偏分析）。", "patch_summary": "占位补丁"})
        return session.to_report()
