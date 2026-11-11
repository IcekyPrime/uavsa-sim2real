"""ROS1 ↔ ROS2 话题适配层（v1.0 方案 1）。

真实桥接流程（示例，需 ROS 环境配合）：
  1. 订阅 sim_bridge 推送的传感器数据（里程计 / 点云，JSON over HTTP）。
  2. 将 JSON 发布为 ROS1 话题（/odom、/point_cloud）喂给 EGO-Planner。
  3. 订阅 EGO-Planner 的规划轨迹话题，序列化回传给 sim_bridge。

v1.0 中本模块提供数据契约与转换函数；真实 ROS 发布订阅需在镜像内
source ROS Noetic 后启用（参见 docker2/README.md 方案 1）。
"""
from __future__ import annotations

from typing import Dict, List


def odom_to_ros(odom: Dict) -> Dict:
    """把 sim_bridge 的里程计 JSON 转为 ROS nav_msgs/Odometry 近似结构。"""
    return {
        "pose": {
            "position": {
                "x": odom.get("x", 0.0),
                "y": odom.get("y", 0.0),
                "z": odom.get("z", 0.0),
            },
            "orientation": odom.get("orientation", {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0}),
        }
    }


def pointcloud_to_ros(points: List[List[float]]) -> Dict:
    """点云列表转为 ROS sensor_msgs/PointCloud2 近似结构（简化版）。"""
    return {"points": [{"x": p[0], "y": p[1], "z": p[2]} for p in points]}


def trajectory_from_ros(ros_traj: List[Dict]) -> List[Dict]:
    """把 EGO-Planner 输出轨迹转为统一结构。"""
    return [
        {"t": p.get("t", 0.0), "x": p.get("x", 0.0), "y": p.get("y", 0.0), "z": p.get("z", 0.0)}
        for p in ros_traj
    ]
