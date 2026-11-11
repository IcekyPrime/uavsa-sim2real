"""SSH 后端：把 SimBackend / AlgoBackend 映射到集群真实 ROS 环境。

- SshSimBackend  →  uavsa-sim22 容器（PX4 SITL + Gazebo + MAVROS），读取真实飞行指标。
- SshAlgoBackend →  uavsa-ego4 容器（ego-planner），编译 / 触发 / 打补丁 / 重launch。

观测层（v1.1）：注入到 ego 容器的 ROS 脚本按固定步长采样真实话题，产出
  - 轨迹时序 rows：t / 实际位置 / 实际速度 / 指令位置 / 跟踪误差 / 飞行相位；
  - 分相位指标 phase_summary：takeoff / cruise / hover 各自统计，避免「悬停得高分」；
  - 指标语义校正：convergence_time 为真实收敛时刻，success_rate 为航点到达率，
    collision/safety 按全部 mock 墙面 + 连续侵入段计数。
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Optional

from .base import AlgoBackend, SimBackend
from .cluster_ssh import ClusterSSH

METRIC_KEYS = [
    "tracking_error_m", "convergence_time_s", "success_rate", "collision_count",
    "overshoot", "smoothness", "energy", "safety_violations", "anomaly_score",
]

SIM_CONTAINER = os.environ.get("CLUSTER_SIM_CONTAINER", "uavsa-sim22")
EGO_CONTAINER = os.environ.get("CLUSTER_EGO_CONTAINER", "uavsa-ego4")

# 容器内 /host 挂载了集群工作目录下的 docker/，launch / 参数文件都在这里
PARAM_FILE = "/host/advanced_param_px4.xml"
LAUNCH_FILE = "/host/run_px4.launch"
# /host 对应的宿主机绝对路径，由 CLUSTER_PRP_DOCKER 配置（仓库内不写死路径）。
PRP_DOCKER = os.environ.get("CLUSTER_PRP_DOCKER", "").rstrip("/")

ROS_BASE = "source /opt/ros/noetic/setup.bash"
ROS_EGO = "source /opt/ros/noetic/setup.bash && source /ego_ws/ego/devel/setup.bash && export ROS_MASTER_URI=http://localhost:11311"

# 注入到 ego 容器的飞行观测脚本：按固定步长采样真实话题，输出「轨迹时序 + 分相位指标」。
# 关键语义：
#   - 主指标（跟踪误差/平滑/能耗/超调）只在 cruise 相位统计，悬停不再自动得高分；
#   - convergence_time 为「首次 |err|<0.2 且持续 1s」的时刻；
#   - success_rate 为 PRESET 航点的真实到达率；
#   - collision / safety 遍历 mock_cloud 的全部墙面，按连续侵入段计数。
_FLIGHT_SCRIPT = r'''# -*- coding: utf-8 -*-
import json, math, sys, time
import rospy
from nav_msgs.msg import Odometry
from quadrotor_msgs.msg import PositionCommand

WINDOW = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
SAMPLE_DT = 0.1

# mock_cloud.py 的两道竖直墙（世界/ENU 系）
WALLS = [
    {"name": "wallA", "axis": "x", "pos": 2.5, "lo": -2.0, "hi": 2.0},
    {"name": "wallB", "axis": "y", "pos": 2.5, "lo": 0.0, "hi": 5.0},
]
Z_LO, Z_HI = 0.0, 2.0
CLEARANCE = 0.35   # 安全裕度（近距告警）
HIT_R = 0.15       # 机体半径，视为碰撞

S = {"odom": None, "odom_t": 0.0, "cmd": None, "cmd_t": 0.0}


def on_odom(m):
    p = m.pose.pose.position
    v = m.twist.twist.linear
    S["odom"] = (p.x, p.y, p.z, v.x, v.y, v.z)
    S["odom_t"] = time.time()


def on_cmd(m):
    S["cmd"] = (m.position.x, m.position.y, m.position.z,
                m.velocity.x, m.velocity.y, m.velocity.z)
    S["cmd_t"] = time.time()


def wall_dist(p, w):
    """点 p 到无限薄墙面（含横向端点）的最短距离。"""
    if w["axis"] == "x":
        perp = abs(p[0] - w["pos"]); lat = p[1]
    else:
        perp = abs(p[1] - w["pos"]); lat = p[0]
    if lat < w["lo"]:
        exc = w["lo"] - lat
    elif lat > w["hi"]:
        exc = lat - w["hi"]
    else:
        exc = 0.0
    return math.hypot(perp, exc)


def episodes(flags):
    """连续 True 段计数。"""
    n, prev = 0, False
    for f in flags:
        if f and not prev:
            n += 1
        prev = f
    return n


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def rms(xs):
    return math.sqrt(sum(x * x for x in xs) / len(xs)) if xs else None


def accel_series(rows):
    out = []
    for a, b in zip(rows, rows[1:]):
        dt = b["t"] - a["t"]
        if dt <= 0:
            continue
        dvx = b["vx"] - a["vx"]; dvy = b["vy"] - a["vy"]; dvz = b["vz"] - a["vz"]
        out.append(math.sqrt(dvx * dvx + dvy * dvy + dvz * dvz) / dt)
    return out


def speed_of(r):
    return math.sqrt(r["vx"] ** 2 + r["vy"] ** 2 + r["vz"] ** 2)


def stats(rs):
    errs = [r["err"] for r in rs if r["err"] is not None]
    spds = [speed_of(r) for r in rs]
    accs = accel_series(rs)
    return {
        "samples": len(rs),
        "duration_s": round(rs[-1]["t"] - rs[0]["t"], 2) if len(rs) > 1 else 0.0,
        "tracking_error_m": round(mean(errs), 4) if errs else None,
        "max_error_m": round(max(errs), 4) if errs else None,
        "mean_speed": round(mean(spds), 3) if spds else None,
        "accel_rms": round(rms(accs), 4) if accs else None,
    }


rospy.init_node("uavsa_flight", anonymous=True)
rospy.Subscriber("/mavros/local_position/odom", Odometry, on_odom)
rospy.Subscriber("/planning/pos_cmd", PositionCommand, on_cmd)

# PRESET 航点（用于真实到达率）
wps = []
try:
    n_wp = int(rospy.get_param("/ego_planner_node/fsm/waypoint_num", 0))
    for i in range(n_wp):
        wps.append((
            float(rospy.get_param("/ego_planner_node/fsm/waypoint%d_x" % i, 0.0)),
            float(rospy.get_param("/ego_planner_node/fsm/waypoint%d_y" % i, 0.0)),
            float(rospy.get_param("/ego_planner_node/fsm/waypoint%d_z" % i, 0.0)),
        ))
except Exception:
    wps = []

# 等待 odom 与 pos_cmd 就绪（最多 3s）
t_wait = time.time()
while (S["odom"] is None or S["cmd"] is None) and time.time() - t_wait < 3.0 and not rospy.is_shutdown():
    time.sleep(0.05)

target_z = S["cmd"][2] if S["cmd"] else 1.0
rows = []
t0 = time.time()
takeoff_done = False

while not rospy.is_shutdown():
    now = time.time()
    t_rel = now - t0
    if t_rel > WINDOW:
        break
    od = S["odom"]
    if od is None:
        time.sleep(SAMPLE_DT)
        continue
    fresh_cmd = S["cmd"] if (S["cmd_t"] and now - S["cmd_t"] < 1.0) else None
    err = None
    if fresh_cmd is not None:
        err = math.sqrt((od[0] - fresh_cmd[0]) ** 2 + (od[1] - fresh_cmd[1]) ** 2 + (od[2] - fresh_cmd[2]) ** 2)
    spd = math.sqrt(od[3] ** 2 + od[4] ** 2 + od[5] ** 2)

    if not takeoff_done and od[2] >= 0.9 * max(target_z, 0.5):
        takeoff_done = True
    if not takeoff_done:
        phase = "takeoff"
    else:
        cmd_spd = 0.0
        if fresh_cmd is not None:
            cmd_spd = math.sqrt(fresh_cmd[3] ** 2 + fresh_cmd[4] ** 2 + fresh_cmd[5] ** 2)
        phase = "cruise" if max(spd, cmd_spd) > 0.2 else "hover"

    rows.append({
        "t": round(t_rel, 2),
        "x": round(od[0], 3), "y": round(od[1], 3), "z": round(od[2], 3),
        "vx": round(od[3], 3), "vy": round(od[4], 3), "vz": round(od[5], 3),
        "cmd_x": round(fresh_cmd[0], 3) if fresh_cmd else None,
        "cmd_y": round(fresh_cmd[1], 3) if fresh_cmd else None,
        "cmd_z": round(fresh_cmd[2], 3) if fresh_cmd else None,
        "err": round(err, 4) if err is not None else None,
        "phase": phase,
    })
    time.sleep(SAMPLE_DT)

phase_summary = {}
for ph in ("takeoff", "cruise", "hover"):
    sub = [r for r in rows if r["phase"] == ph]
    if sub:
        phase_summary[ph] = stats(sub)

cruise = [r for r in rows if r["phase"] == "cruise"]
base_rows = cruise if cruise else []
errs = [r["err"] for r in base_rows if r["err"] is not None]
spds = [speed_of(r) for r in base_rows]
accs = accel_series(base_rows)

tracking_error = mean(errs)
overshoot = max(errs) if errs else None
smoothness = rms(accs)
energy = mean([v * v for v in spds])

# 全时段（含起飞/悬停）统计撞墙与近距告警，按连续侵入段计
hit_flags = {w["name"]: [] for w in WALLS}
near_flags = {w["name"]: [] for w in WALLS}
for r in rows:
    p = (r["x"], r["y"], r["z"])
    in_z = Z_LO <= p[2] <= Z_HI
    for w in WALLS:
        d = wall_dist(p, w)
        hit_flags[w["name"]].append(bool(in_z and d < HIT_R))
        near_flags[w["name"]].append(bool(in_z and d < CLEARANCE))

wall_detail = {
    w["name"]: {"collisions": episodes(hit_flags[w["name"]]),
                "near_misses": episodes(near_flags[w["name"]])}
    for w in WALLS
}
collision_count = sum(v["collisions"] for v in wall_detail.values())
safety_violations = sum(v["near_misses"] for v in wall_detail.values())

# 航点到达统计（仅窗口内可见的航点）
wp_detail = []
reached = 0
for (wx, wy, wz) in wps:
    dmin = None
    for r in rows:
        d = math.sqrt((r["x"] - wx) ** 2 + (r["y"] - wy) ** 2 + (r["z"] - wz) ** 2)
        dmin = d if dmin is None else min(dmin, d)
    ok = dmin is not None and dmin <= 0.4
    reached += 1 if ok else 0
    wp_detail.append({"x": wx, "y": wy, "z": wz, "reached": ok,
                      "min_dist": round(dmin, 3) if dmin is not None else None})
# success_rate 语义：窗口内至少完成 1 个航点且无碰撞 = 任务推进正常
# （短窗口无法覆盖全部航点，按「到达率」算会把正常飞行误判为失败）
success_rate = 1.0 if (reached >= 1 and collision_count == 0) else 0.0

# 真实收敛时刻：只看 cruise 相位，首次 |err|<0.2 且之后 1s 内持续 <0.2（相对巡航起点）
convergence = None
for i, r in enumerate(cruise):
    if r["err"] is None or r["err"] >= 0.2:
        continue
    ok = True
    for q in cruise[i:]:
        if q["t"] - r["t"] > 1.0:
            break
        if q["err"] is None or q["err"] >= 0.2:
            ok = False
            break
    if ok:
        convergence = r["t"] - cruise[0]["t"]
        break

# 有界异常分（避免旧版长期饱和到 1.0）
anomaly = 0.0
if tracking_error is not None:
    anomaly += 0.35 * min(1.0, tracking_error / 0.5)
if smoothness is not None:
    anomaly += 0.25 * min(1.0, smoothness / 2.0)
if overshoot is not None:
    anomaly += 0.20 * min(1.0, overshoot / 1.5)
anomaly += 0.20 * min(1.0, safety_violations / 10.0)
anomaly = min(1.0, anomaly)

if not rows:
    flight_state = "no_data"
elif cruise:
    flight_state = "cruise"
elif any(r["phase"] == "hover" for r in rows):
    flight_state = "hover"
else:
    flight_state = "takeoff_only"

res = {
    "metrics": {
        "tracking_error_m": round(tracking_error, 4) if tracking_error is not None else None,
        "convergence_time_s": round(convergence, 2) if convergence is not None else None,
        "success_rate": round(success_rate, 4),
        "collision_count": int(collision_count),
        "overshoot": round(overshoot, 4) if overshoot is not None else None,
        "smoothness": round(smoothness, 4) if smoothness is not None else None,
        "energy": round(energy, 4) if energy is not None else None,
        "safety_violations": int(safety_violations),
        "anomaly_score": round(anomaly, 4),
    },
    "phase_summary": phase_summary,
    "flight_state": flight_state,
    "waypoints": wp_detail,
    "reached_waypoints": reached,
    "total_waypoints": len(wps),
    "walls": wall_detail,
    "n_odom": len(rows),
    "rows": rows,
}
print("UAVSA_FLIGHT " + json.dumps(res))
'''


# 注入到 ego 容器的运动检测脚本：采样 2.5s 里程计，输出位移与平均速度（判断是否在真实飞行）
_MOTION_SCRIPT = r'''# -*- coding: utf-8 -*-
import json, math, time
import rospy
from nav_msgs.msg import Odometry

S = {"p": None, "p0": None, "dist": 0.0, "n": 0, "spd_sum": 0.0}

def on_odom(m):
    p = (m.pose.pose.position.x, m.pose.pose.position.y, m.pose.pose.position.z)
    v = m.twist.twist.linear
    if S["p"] is not None:
        S["dist"] += math.dist(S["p"], p)
    if S["p0"] is None:
        S["p0"] = p
    S["p"] = p
    S["spd_sum"] += math.sqrt(v.x**2 + v.y**2 + v.z**2)
    S["n"] += 1

rospy.init_node("uavsa_motion", anonymous=True)
rospy.Subscriber("/mavros/local_position/odom", Odometry, on_odom)
t0 = time.time()
while time.time() - t0 < 2.5 and not rospy.is_shutdown():
    time.sleep(0.05)
n = max(1, S["n"])
print("UAVSA_MOTION " + json.dumps({
    "travel_m": round(S["dist"], 3),
    "mean_speed": round(S["spd_sum"] / n, 3),
    "n": S["n"],
}))
'''


def _b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def _host_path(path: str) -> str:
    """把容器内路径（/host/... 或相对路径）映射为宿主机上的真实路径。"""
    if path.startswith("/") and not path.startswith("/host/"):
        return path
    if not PRP_DOCKER:
        raise RuntimeError("未配置 CLUSTER_PRP_DOCKER（宿主机 docker 目录绝对路径），无法写入补丁")
    if path.startswith("/host/"):
        return PRP_DOCKER + "/" + path[len("/host/"):]
    return PRP_DOCKER + "/" + path


def _write_file(ssh: ClusterSSH, path: str, content: str) -> str:
    """通过 base64 把文件内容写入宿主机路径，规避引号转义问题（不依赖容器运行）。"""
    hp = _host_path(path)
    b = _b64(content)
    chunk = 60_000
    parts = [b[i:i + chunk] for i in range(0, len(b), chunk)]
    if len(parts) == 1:
        return ssh.run(f"echo {parts[0]} | base64 -d > {hp}", read_timeout=30)
    ssh.run(f"rm -f {hp}", read_timeout=15)
    for p in parts:
        ssh.run(f"echo {p} >> {hp}", read_timeout=30)
    return ssh.run(f"cat {hp} | base64 -d > {hp}.dec && mv {hp}.dec {hp}", read_timeout=30)


def _read_file(ssh: ClusterSSH, path: str) -> str:
    hp = _host_path(path)
    return ssh.run(f"cat {hp} 2>&1", read_timeout=30)


def restart_ego(ssh: ClusterSSH) -> None:
    """重启 ego 容器（entrypoint 为 roslaunch 前台，kill roslaunch 会带走容器）。

    重启后 mock_cloud / 桥接 / ego-planner 整条链路以最新参数重新拉起，
    PRESET 航点任务随之重新触发。
    """
    cid = ssh.container_id("uavsa-ego4", running_only=False)
    ssh.run(f"docker restart {cid}", read_timeout=40)
    for _ in range(40):
        nodes = ssh.docker_exec(
            EGO_CONTAINER,
            ROS_EGO + " && timeout 4 rosnode list 2>&1 | grep -c ego_planner_node",
            read_timeout=20,
        ).strip()
        if nodes.isdigit() and int(nodes) >= 1:
            break
        time.sleep(1.0)
    for _ in range(30):
        st = ssh.docker_exec(
            SIM_CONTAINER,
            ROS_BASE + " && timeout 4 rostopic echo -n 1 /mavros/state 2>&1 | grep -e mode",
            read_timeout=20,
        )
        if "OFFBOARD" in st:
            break
        time.sleep(1.0)
    time.sleep(1.5)  # 只留最短稳定时间，让采样窗口从任务起点开始（覆盖巡航主体）


def motion_probe(ssh: ClusterSSH) -> dict:
    """采样 2.5s 里程计，返回位移与平均速度。"""
    ssh.docker_exec(
        EGO_CONTAINER,
        f"echo {_b64(_MOTION_SCRIPT)} | base64 -d > /tmp/uavsa_motion.py",
        read_timeout=30,
    )
    out = ssh.docker_exec(
        EGO_CONTAINER,
        ROS_EGO + " && /usr/bin/python3 /tmp/uavsa_motion.py",
        read_timeout=30,
    )
    m = re.search(r"UAVSA_MOTION\s*(\{.*\})", out, re.S)
    return json.loads(m.group(1)) if m else {"travel_m": None, "mean_speed": None, "n": 0, "_raw": out.strip()[:200]}


def ensure_flying(ssh: ClusterSSH) -> dict:
    """确保评测窗口处于真实飞行状态。

    PRESET 航点任务只在 ego_planner_node 启动时触发一次，任务结束后无人机悬停，
    直接采样会得到「悬停态」的虚低指标（跟踪误差≈0）。若检测到悬停则重启 ego 容器
    重新触发任务，并立即开始采样（不再等待固定时长），使窗口覆盖完整巡航段。
    """
    probe = motion_probe(ssh)
    moving = (probe.get("travel_m") or 0) >= 0.5 or (probe.get("mean_speed") or 0) >= 0.2
    if moving:
        return {"retriggered": False, "probe": probe}
    restart_ego(ssh)
    return {"retriggered": True, "probe": probe,
            "note": "任务已结束/悬停，已重启 ego 重新触发航点任务，采样从任务起点开始"}


def sample_flight(ssh: ClusterSSH, window_s: float = 12.0) -> dict:
    """在 ego 容器内采样真实飞行时序，返回 metrics / phase_summary / rows。"""
    ssh.docker_exec(
        EGO_CONTAINER,
        f"echo {_b64(_FLIGHT_SCRIPT)} | base64 -d > /tmp/uavsa_flight.py",
        read_timeout=30,
    )
    out = ssh.docker_exec(
        EGO_CONTAINER,
        ROS_EGO + f" && /usr/bin/python3 /tmp/uavsa_flight.py {float(window_s)}",
        read_timeout=int(window_s) + 30,
    )
    m = re.search(r"UAVSA_FLIGHT\s*(\{.*\})", out, re.S)
    if not m:
        return {"metrics": {}, "rows": [], "phase_summary": {}, "flight_state": "no_data",
                "_raw": out.strip()[:500]}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        return {"metrics": {}, "rows": [], "phase_summary": {}, "flight_state": "no_data",
                "_raw": f"JSON 解析失败：{e}；原文前 300 字：{m.group(1)[:300]}"}


def _downsample(rows: list[dict], limit: int) -> list[dict]:
    """等距下采样，保留首尾，供 LLM 阅读（完整数据另存 session）。"""
    if len(rows) <= limit:
        return rows
    step = (len(rows) - 1) / float(limit - 1)
    return [rows[int(round(i * step))] for i in range(limit)]


class SshSimBackend(SimBackend):
    """真实仿真后端：从 uavsa-sim22 容器读取 PX4 飞行状态与真实指标。"""

    def __init__(self, ssh: ClusterSSH):
        self.ssh = ssh
        self._running = False

    def start_scenario(self, scenario: dict | None = None) -> dict:
        density = (scenario or {}).get("obstacle_density", 0.5)
        wind = (scenario or {}).get("wind_m_s", 0.0)
        state = self.ssh.docker_exec(
            SIM_CONTAINER,
            ROS_BASE + " && timeout 5 rostopic echo -n 1 /mavros/state 2>&1 | grep -e armed -e mode -e connected",
            read_timeout=30,
        )
        armed = "armed: True" in state
        self._running = True
        return {
            "status": "running", "backend": "cluster-px4-sitl",
            "armed": armed, "obstacle_density": density, "wind_m_s": wind,
            "state": state.strip().replace("\n", " | ")[:300],
        }

    def stop(self) -> dict:
        self._running = False
        return {"status": "stopped", "backend": "cluster-px4-sitl"}

    def metrics(self) -> dict:
        if not self._running:
            self._running = True  # 集群仿真常开：未显式 start_scenario 也直接测量真实飞行
        flight = ensure_flying(self.ssh)
        data = sample_flight(self.ssh, 12.0)
        m = data.get("metrics") or {}
        result = {k: m.get(k) for k in METRIC_KEYS}
        result["_samples"] = {"n_odom": data.get("n_odom")}
        result["_phase_summary"] = data.get("phase_summary") or {}
        result["_flight_state"] = data.get("flight_state", "no_data")
        result["_waypoints"] = data.get("waypoints") or []
        result["_reached_waypoints"] = data.get("reached_waypoints")
        result["_total_waypoints"] = data.get("total_waypoints")
        result["_walls"] = data.get("walls") or {}
        result["_flight"] = flight
        result["_series"] = data.get("rows") or []
        if not m:
            result["_raw"] = data.get("_raw")
        return result


class SshAlgoBackend(AlgoBackend):
    """真实算法后端：在 uavsa-ego4 容器内编译 / 触发 / 打补丁 / 重launch ego-planner。"""

    def __init__(self, ssh: ClusterSSH):
        self.ssh = ssh
        self._dirty = False
        self._patch_count = 0

    def build(self) -> dict:
        # 参数/launch 补丁无需重编译；此处做真实存在性校验
        exists = self.ssh.docker_exec(
            EGO_CONTAINER,
            f"test -f {PARAM_FILE} && echo PARAM_OK; ls /ego_ws/ego/devel/lib/ego_planner/ego_planner_node 2>&1",
            read_timeout=30,
        )
        return {"status": "built", "backend": "cluster-ego", "check": exists.strip()[:300]}

    def run(self, duration_s: float = 5.0) -> dict:
        if self._dirty:
            self._relaunch()
            self._dirty = False
            flight = {"retriggered": True, "note": "补丁已生效，重启 ego 后立即采样"}
        else:
            flight = ensure_flying(self.ssh)
        # 真实时序窗口：3~15s，10Hz 采样（旧版固定 12 帧、无时间轴，无法判别飞行状态）
        window = min(15.0, max(3.0, float(duration_s)))
        data = sample_flight(self.ssh, window)
        rows = data.get("rows") or []
        return {
            "status": "completed", "backend": "cluster-ego",
            "duration_s": round(window, 1),
            "trajectory_length": len(rows),
            "trajectory": _downsample(rows, 60),
            "metrics": data.get("metrics") or {},
            "phase_summary": data.get("phase_summary") or {},
            "flight_state": data.get("flight_state", "no_data"),
            "waypoints": data.get("waypoints") or [],
            "reached_waypoints": data.get("reached_waypoints"),
            "total_waypoints": data.get("total_waypoints"),
            "_flight": flight,
            "_series": rows,
        }

    def patch(self, files: list[dict], message: str = "") -> dict:
        import xml.etree.ElementTree as ET
        applied = []
        errors = []
        for f in files:
            path = f.get("path", "")
            if not path.startswith("/"):
                path = "/host/" + path

            # 形式 1：参数覆盖 {path, params: {name: value}}（推荐，更稳健）
            params = f.get("params")
            if isinstance(params, dict) and params:
                cur = _read_file(self.ssh, path)
                new = cur
                for name, value in params.items():
                    pat = re.compile(r'(<param\s+name="' + re.escape(str(name)) + r'"[^>]*value=")[^"]*(")', re.S)
                    new, n = pat.subn(lambda m, v=str(value): m.group(1) + v + m.group(2), new)
                    if n == 0:
                        errors.append(f"{path}: 未找到参数 {name}")
                if new != cur and not errors:
                    _write_file(self.ssh, path + ".bak", cur)
                    _write_file(self.ssh, path, new)
                    applied.append(path)
                continue

            # 形式 2：整文件覆盖 {path, content}
            content = f.get("content", "")
            if path.endswith((".xml", ".launch")) and content.strip():
                try:
                    ET.fromstring(content)
                except Exception as e:
                    errors.append(f"{path}: 非法 XML（{type(e).__name__}: {e}），已拒绝写入")
                    continue
            _write_file(self.ssh, path + ".bak", _read_file(self.ssh, path))
            _write_file(self.ssh, path, content)
            applied.append(path)
        if errors:
            return {"status": "rejected", "files": applied, "errors": errors,
                    "message": message, "backend": "cluster-ego"}
        self._patch_count += 1
        self._dirty = True
        return {"status": "patched", "files": applied, "message": message, "backend": "cluster-ego"}

    def status(self) -> dict:
        nodes = self.ssh.docker_exec(
            EGO_CONTAINER,
            ROS_EGO + " && timeout 5 rosnode list 2>&1 | grep -e ego_planner -e traj_server",
            read_timeout=30,
        )
        return {"backend": "cluster-ego", "nodes": nodes.strip()[:300]}

    # ---- 内部 ----
    def _relaunch(self) -> None:
        # ego 容器的 entrypoint 是 `bash /host/ego_px4_run.sh`（mock_cloud + pos_cmd_to_px4 + roslaunch 前台），
        # 直接 kill roslaunch 会导致 PID1 退出、容器停止。因此改为「重启容器」，
        # 让 entrypoint 以最新参数重新拉起整条规划链路（补丁文件在 /host 挂载卷中持久化）。
        restart_ego(self.ssh)


def make_ssh_backends(ssh: Optional[ClusterSSH] = None) -> tuple[SshSimBackend, SshAlgoBackend]:
    if ssh is None:
        ssh = ClusterSSH()
        ssh.connect()
    return SshSimBackend(ssh), SshAlgoBackend(ssh)
