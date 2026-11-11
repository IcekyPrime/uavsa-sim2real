"""轻量知识库检索（RAG）与故障案例沉淀。

无重依赖：哈希 n-gram + IDF 加权 + 余弦相似度，可在 Docker / 本地统一运行。

v2 改进：
  - 词法保留 `/` 与 `_`，参数名（如 optimization/lambda_smooth）可整体命中；
  - 语料级 IDF，稀有参数名权重更高；
  - 正文与标题分别向量化，标题命中额外加权；
  - 参数名精确匹配加权；
  - 最低相关度阈值，低分噪声直接丢弃；
  - 文件变更自动重建索引，无需重启进程；
  - 会话结束可把「症状/补丁/结果」追加为案例（append_case）。
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # 仅用于类型提示，避免运行期循环导入
    from ..memory import Session

_DIM = 2048
_MIN_SCORE = 0.09          # 低于该相关度视为噪声
_MIN_COVERAGE = 0.22       # 查询实词在片段中的最低覆盖率
_HEADING_WEIGHT = 0.28     # 标题向量在总分中的占比
_PARAM_BOOST = 0.25        # 每个精确命中的参数名加分
_PARAM_BOOST_CAP = 0.5
_PHRASE_BOOST = 0.15       # 整句精确出现

# 单字停用词：避免「不/的/是」这类高频字造成虚假命中
_STOP_CJK = set("的了是在有和与或不就都要会什么如何是否这个那个可以我们你们他们以及对于通过一个进行需要能够可能如果因为所以但是而且并且")


def _tokenize(text: str) -> list[str]:
    """中文按字、英文按词（保留参数名里的 / _ . -）。"""
    text = text.lower()
    words = re.findall(r"[a-z0-9_\-\./]+", text)
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    return words + cjk


def _hash_token(token: str) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % _DIM


def _raw_vec(tokens: list[str]) -> np.ndarray:
    """TF 计数向量（含相邻二元组）。"""
    vec = np.zeros(_DIM, dtype=np.float32)
    if not tokens:
        return vec
    grams = tokens + [f"{tokens[i]} {tokens[i + 1]}" for i in range(len(tokens) - 1)]
    for g in grams:
        vec[_hash_token(g)] += 1.0
    return vec


def _normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


class KnowledgeBase:
    def __init__(self, knowledge_dir: Path):
        self.knowledge_dir = Path(knowledge_dir)
        self._chunks: list[dict] = []
        self._body: np.ndarray | None = None
        self._heading: np.ndarray | None = None
        self._idf: np.ndarray | None = None
        self._mtime = 0.0
        self._load()

    # ---------- 索引 ----------
    def _chunk_text(self, text: str, source: str) -> list[dict]:
        """按标题分节、按空行分段；heading 与正文严格配对。"""
        chunks: list[dict] = []

        def push(heading: str, body: str):
            body = body.strip()
            if not body:
                return
            for para in re.split(r"\n\s*\n", body):
                para = para.strip()
                if len(para) < 8:
                    continue
                chunks.append({
                    "text": f"{heading}\n{para}".strip() if heading else para,
                    "heading": heading,
                    "source": source,
                })

        sections = re.split(r"(?m)^(#{1,4}\s+.*)$", text)
        push("", sections[0] if sections else "")
        for i in range(1, len(sections), 2):
            heading = sections[i].strip().lstrip("#").strip()
            body = sections[i + 1] if i + 1 < len(sections) else ""
            push(heading, body)
        return chunks

    def _load(self):
        self._chunks = []
        newest = 0.0
        if not self.knowledge_dir.exists():
            self._body = self._heading = self._idf = None
            self._mtime = 0.0
            return
        for f in self.knowledge_dir.rglob("*"):
            if f.suffix.lower() not in (".md", ".txt"):
                continue
            try:
                text = f.read_text(encoding="utf-8")
                newest = max(newest, f.stat().st_mtime)
            except Exception:
                continue
            self._chunks.extend(self._chunk_text(text, f.name))

        if not self._chunks:
            self._body = self._heading = self._idf = None
            self._mtime = newest
            return

        n = len(self._chunks)
        raw_body = np.stack([_raw_vec(_tokenize(c["text"])) for c in self._chunks])
        raw_head = np.stack([_raw_vec(_tokenize(c["heading"])) for c in self._chunks])

        # 语料级 IDF：稀有词（通常是参数名）权重更高
        df = (raw_body > 0).sum(axis=0).astype(np.float32)
        idf = np.log((n + 1.0) / (df + 1.0)) + 1.0
        self._idf = idf

        self._body = np.stack([_normalize(v * idf) for v in raw_body])
        self._heading = np.stack([_normalize(v * idf) for v in raw_head])
        self._mtime = newest

        for c in self._chunks:
            c["params"] = set(re.findall(r"`([^`]*[/_][^`]*)`", c["text"]))
            c["lower"] = c["text"].lower()
            c["terms"] = set(_tokenize(c["text"]))
            c["head_terms"] = set(_tokenize(c["heading"]))

    @property
    def size(self) -> int:
        return len(self._chunks)

    def rebuild_index(self):
        """强制重建索引（新增文档或案例后调用）。"""
        self._load()

    def refresh_if_changed(self):
        """文档有更新时自动重建（按 mtime 判断）。"""
        newest = 0.0
        if self.knowledge_dir.exists():
            for f in self.knowledge_dir.rglob("*"):
                if f.suffix.lower() in (".md", ".txt"):
                    try:
                        newest = max(newest, f.stat().st_mtime)
                    except OSError:
                        pass
        if newest > self._mtime + 1e-6:
            self._load()

    def titles(self) -> list[dict]:
        """按来源列出文档与标题，供检索未命中时引导换词。"""
        out: dict[str, set] = {}
        for c in self._chunks:
            out.setdefault(c["source"], set())
            if c["heading"]:
                out[c["source"]].add(c["heading"])
        return [{"source": k, "headings": sorted(v)[:8]} for k, v in sorted(out.items())]

    # ---------- 检索 ----------
    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        self.refresh_if_changed()
        if not self._chunks or self._body is None:
            return []
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        q_vec = _normalize(_raw_vec(q_tokens) * self._idf)
        body_scores = self._body @ q_vec
        head_scores = self._heading @ q_vec
        scores = 0.72 * body_scores + _HEADING_WEIGHT * head_scores

        # 查询实词（去掉高频单字），用于覆盖率判定
        q_terms = {t for t in q_tokens if not (len(t) == 1 and t in _STOP_CJK)} or set(q_tokens)
        # 参数名精确匹配：把 `xxx/yyy`、`xxx_yyy` 这类查询词直接与片段比对
        q_params = [t for t in set(q_tokens) if ("/" in t or "_" in t) and len(t) >= 5]
        q_phrase = query.strip().lower()

        cand = np.argsort(-scores)[: max(top_k * 4, 12)]
        results = []
        for idx in cand:
            i = int(idx)
            s = float(scores[i])
            if s <= 0:
                continue
            chunk = self._chunks[i]

            overlap = q_terms & chunk["terms"]
            coverage = len(overlap) / max(1, len(q_terms))
            head_cov = len(q_terms & chunk["head_terms"]) / max(1, len(q_terms))

            match = []
            anchored = False
            if head_cov >= 0.2:
                match.append("heading")
                anchored = True
            if q_params:
                hit = [p for p in q_params if p in chunk["params"] or p in chunk["lower"]]
                if hit:
                    s += min(_PARAM_BOOST_CAP, _PARAM_BOOST * len(hit))
                    match.append("param:" + ",".join(hit[:3]))
                    anchored = True
            if len(q_phrase) >= 4 and q_phrase in chunk["lower"]:
                s += _PHRASE_BOOST
                match.append("phrase")
                anchored = True

            # 覆盖率不足且没有任何强锚点 → 视为噪声
            if coverage < _MIN_COVERAGE and not anchored:
                continue
            if s < _MIN_SCORE:
                continue
            results.append({
                "text": chunk["text"][:800],
                "source": chunk["source"],
                "heading": chunk["heading"],
                "score": round(min(1.5, s), 4),
                "coverage": round(coverage, 2),
                "match": match or ["body"],
            })

        results.sort(key=lambda r: -r["score"])
        return results[:top_k]

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """别名：供 search_algorithm 工具复用。"""
        return self.retrieve(query, top_k)


# ---------- 故障案例自动沉淀 ----------

def _num(v) -> str:
    if isinstance(v, (int, float)):
        return f"{v:g}"
    return "—"


def build_case(session: "Session") -> tuple[str, str] | None:
    """从会话中提取「症状 / 补丁 / 结果」案例。无有效对比时返回 None。"""
    if len(session.metrics_history) < 2 or not session.patch_history:
        return None

    # 只在补丁真正写入成功时记录（被拒绝的补丁不产生案例）
    applied = [p for p in session.patch_history if p.get("status") in (None, "patched")]
    if not applied:
        return None

    # 只取 cruise 相位且误差有效的两轮指标，悬停数据不参与结论
    valid = [
        m for m in session.metrics_history
        if m.get("tracking_error_m") is not None and m.get("_flight_state") in (None, "cruise")
    ]
    if len(valid) < 2:
        return None
    first, last = valid[0], valid[-1]

    def sig_parts() -> str:
        patches = []
        for p in applied:
            for ch in p.get("changes", []):
                if ch.get("params"):
                    patches.append(ch["path"] + ":" + ",".join(sorted(ch["params"])))
                else:
                    patches.append(ch["path"])
        raw = "|".join([session.goal, *patches,
                        str(first.get("tracking_error_m")), str(last.get("tracking_error_m"))])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    patch_lines = []
    for p in applied:
        for ch in p.get("changes", []):
            if ch.get("params"):
                kv = ", ".join(f"{k}={v}" for k, v in ch["params"].items())
                patch_lines.append(f"{ch['path']} ← {kv}")
            else:
                patch_lines.append(f"{ch['path']}（整文件覆盖 {ch.get('content_chars', 0)} 字符）")
    if not patch_lines:
        return None

    symptoms = []
    if first.get("_flight_state"):
        symptoms.append(f"flight_state={first['_flight_state']}")
    symptoms += [
        f"巡航跟踪误差 {_num(first.get('tracking_error_m'))} m",
        f"碰撞 {_num(first.get('collision_count'))}",
        f"安全告警 {_num(first.get('safety_violations'))}",
        f"平滑度 {_num(first.get('smoothness'))}",
    ]

    results = [
        f"跟踪误差 {_num(first.get('tracking_error_m'))} → {_num(last.get('tracking_error_m'))} m",
        f"碰撞 {_num(first.get('collision_count'))} → {_num(last.get('collision_count'))}",
        f"安全告警 {_num(first.get('safety_violations'))} → {_num(last.get('safety_violations'))}",
        f"平滑度 {_num(first.get('smoothness'))} → {_num(last.get('smoothness'))}",
    ]

    # 结论打分：碰撞优先，其次巡航误差
    score = 0
    for key, weight in (("collision_count", 2), ("safety_violations", 1)):
        a, b = first.get(key), last.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if b < a:
                score += weight
            elif b > a:
                score -= weight
    e0, e1 = first.get("tracking_error_m"), last.get("tracking_error_m")
    if isinstance(e0, (int, float)) and isinstance(e1, (int, float)) and e0 > 0:
        rel = (e1 - e0) / e0
        if rel < -0.05:
            score += 2
        elif rel > 0.05:
            score -= 2

    verdict = ("有效" if score >= 3 else
               "部分有效" if score >= 1 else
               "无明显变化" if score == 0 else "变差")

    ts = time.strftime("%Y-%m-%d %H:%M")
    goal = session.goal.strip().replace("\n", " ")[:60]
    block = "\n".join([
        f"## {ts} · {goal}",
        f"- 症状：{'；'.join(symptoms)}",
        f"- 补丁：{'；'.join(patch_lines)}",
        f"- 结果：{'；'.join(results)}（相位均为 cruise）",
        f"- 结论：{verdict}",
        f"<!-- sig:{sig_parts()} -->",
        "",
    ])
    return sig_parts(), block


def append_case(knowledge_dir: Path, session: "Session") -> Path | None:
    """把会话案例追加到 knowledge/cases/auto-cases.md（按签名去重）。"""
    built = build_case(session)
    if not built:
        return None
    sig, block = built
    case_dir = Path(knowledge_dir) / "cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    path = case_dir / "auto-cases.md"
    header = ("# Agent 自动沉淀案例\n\n"
              "> 由会话结束自动追加；仅记录「至少 1 次补丁 + 至少 2 轮指标」的会话，按签名去重。\n\n")
    existing = ""
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except Exception:
            existing = ""
    if f"<!-- sig:{sig} -->" in existing:
        return None
    if not existing:
        path.write_text(header + block, encoding="utf-8")
    else:
        with path.open("a", encoding="utf-8") as f:
            f.write("\n" + block)
    return path
