# docker2 — 被测算法（EGO-Planner）

## 说明

docker2 承载被测算法，通过 `algo_bridge` 服务向 agent 暴露标准接口：
`build`（编译）、`run`（运行）、`patch`（打补丁）、`status`（状态）。

EGO-Planner 是 ROS1（Noetic）包，而 docker1 使用 ROS2 Jazzy + Gazebo Harmonic。
两者通信的桥接方案如下。

## ROS1 ↔ ROS2 桥接说明

### 方案 1：话题适配层（v1.0 采用）

`algo_bridge/bridge_ros.py` 提供「数据适配层」：

1. `sim_bridge` 把仿真中的里程计 / 点云以 JSON 推给 `algo_bridge`。
2. `algo_bridge` 将 JSON 转为 ROS1 话题（`/odom`、`/point_cloud`）喂给 EGO-Planner。
3. EGO-Planner 产出规划轨迹，`algo_bridge` 再以 JSON 回传 `sim_bridge` 用于跟踪执行与指标计算。

此方案不要求 ros1_bridge 等重型组件，闭环可控，代价是消息需序列化转发。

### 方案 2：ros1_bridge（后续版本）

在 docker1 内启动 `ros1_bridge`，做 DDS（ROS2）↔ TCPROS（ROS1）双向映射，
可获得原生话题级别的互操作，适合多节点复杂算法。

## 目录

- `algo_bridge/main.py`：FastAPI 服务（build / run / patch / status）。
- `algo_bridge/planner.py`：EGO-Planner 封装（进程控制）。
- `algo_bridge/bridge_ros.py`：话题适配层（方案 1）。

## 编译被测算法

```bash
docker compose exec docker2 bash -lc "source /opt/ros/noetic/setup.bash && cd /workspace/ego-planner && catkin_make"
```

> 官方 EGO-Planner 完整仿真依赖 `uav_simulator` + PX4 + Gazebo classic，较重；
> 本平台将其拆到 docker1（仿真）+ docker2（算法），故 docker2 只编译 planner 本体。
