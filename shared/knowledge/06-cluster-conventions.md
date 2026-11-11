# 集群拓扑与约定

本平台的真实仿真跑在集群节点（节点名由 `CLUSTER_SSH_NODE` 配置），工作目录由 `CLUSTER_PRP_DOCKER` 指定。
Agent 通过 SSH（堡垒机 → 计算节点）在用户自己的两个容器内执行命令。

## 1. 两个容器

| 容器名（含前缀） | 简称 | 职责 | 关键进程 |
|------------------|------|------|----------|
| `ai_<user>_uavsa-sim22` | sim22 | 物理仿真 + 飞控 | Gazebo Classic 9、PX4 SITL、MAVROS |
| `ai_<user>_uavsa-ego4` | ego4 | 感知规划 + 控制回传 | ego_planner、traj_server、mock_cloud、pos_cmd_to_px4、setpoint_holder |

两容器均以 `--network host` 运行，共享 `localhost:11311` 的 ROS master，因此 ego4 可以直接订阅 sim22 的话题。

## 2. 硬性约定

1. **docker exec 必须用容器 ID，不能用容器名**：集群 docker 包装器只允许本用户容器，
   用名字会报「不属于您的容器」。先 `docker ps --format '{{.ID}}|{{.Names}}'` 取 ID。
2. 只操作 `ai_<user>_` 前缀的容器，不要影响其他用户。
3. ego4 的 entrypoint 是前台 `roslaunch`，**结束它会导致容器退出**；要重启用 `docker restart <ID>`。
4. 补丁写在宿主机挂载卷（`/host` → `PRP/docker`），容器重启后仍然有效。

## 3. 路径映射

| 容器内 | 宿主机 |
|--------|--------|
| `/host/advanced_param_px4.xml` | `PRP/docker/advanced_param_px4.xml` |
| `/host/run_px4.launch` | `PRP/docker/run_px4.launch` |
| `/host/ego_px4_run.sh` | `PRP/docker/ego_px4_run.sh`（容器启动脚本） |
| `/host/mock_cloud.py` | `PRP/docker/mock_cloud.py`（两道墙点云） |
| `/host/pos_cmd_to_px4.py` | `PRP/docker/pos_cmd_to_px4.py`（控制回传桥） |
| `/ego_ws/ego/` | ego-planner 工作空间（容器内） |

`patch_algorithm` 的相对路径会自动加 `/host/` 前缀，因此传 `advanced_param_px4.xml` 即可。

## 4. 关键话题

| 话题 | 类型 | 频率 | 用途 |
|------|------|------|------|
| `/mavros/local_position/odom` | `nav_msgs/Odometry` | ~30 Hz | 实际位姿（ENU） |
| `/planning/pos_cmd` | `quadrotor_msgs/PositionCommand` | ~100 Hz | 规划位置指令 |
| `/planning/bspline` | `ego_planner/Bspline` | 事件驱动 | 规划轨迹 |
| `/mock_cloud` | `sensor_msgs/PointCloud2` | 10 Hz | 障碍点云（两道墙） |
| `/mavros/setpoint_raw/local` | `mavros_msgs/PositionTarget` | 50 Hz | 控制回传 setpoint |
| `/mavros/state` | `mavros_msgs/State` | ~1 Hz | armed / mode / connected |

## 5. 生命周期与时序

1. `docker restart ego4` 后，entrypoint 依次启动 `mock_cloud`、`pos_cmd_to_px4`、`roslaunch run_px4.launch`。
2. ego-planner 的 PRESET 航点任务**只在节点启动时触发一次**；任务飞完就悬停，不会自动重跑。
3. 因此每次需要「从任务起点开始观测」时，都要重启 ego4。
4. 时间量级参考：容器重启 + 节点就绪约 10–20 s；完整 4 航点任务约 30 s；单次观测窗口 12 s。
5. `pos_cmd_to_px4` 会先发 50 帧预置 setpoint，再切 OFFBOARD + ARM；切换前无人机可能仍在旧状态。

## 6. 常用命令

```bash
# 容器状态
docker ps --format '{{.Names}}|{{.Status}}' | grep ai_<user>_

# 节点
docker exec <egoID> bash -lc 'source /opt/ros/noetic/setup.bash && source /ego_ws/ego/devel/setup.bash && export ROS_MASTER_URI=http://localhost:11311 && rosnode list'

# 飞行状态
docker exec <simID> bash -lc 'source /opt/ros/noetic/setup.bash && timeout 5 rostopic echo -n 1 /mavros/state'

# 当前指令与位置
docker exec <egoID> bash -lc 'source /opt/ros/noetic/setup.bash && source /ego_ws/ego/devel/setup.bash && export ROS_MASTER_URI=http://localhost:11311 && timeout 5 rostopic echo -n 1 /planning/pos_cmd'

# 参数
docker exec <egoID> bash -lc '... && rosparam get /ego_planner_node/optimization/lambda_smooth'

# FSM 日志
docker logs --tail 60 <egoID>
```

## 7. 已知坑

| 坑 | 说明 |
|----|------|
| 用容器名 exec | 报「不属于您的容器」，必须用 ID |
| kill roslaunch | 容器直接退出，必须 `docker restart` |
| 改参数不重启 | 参数在启动时加载，不重启不生效 |
| PRESET 只触发一次 | 任务结束即悬停，需重启才能重测 |
| Gazebo 时间跳变 | 录制 state.log 时不要用 `--record_period`，用 SIGINT 手动结束 |
| mock 墙无碰撞体 | 穿墙不会物理碰撞，碰撞指标是几何近似 |
