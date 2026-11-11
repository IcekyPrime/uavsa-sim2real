#!/usr/bin/env bash
set -e

echo "[docker2] entrypoint: starting algo_bridge"

# source ROS Noetic
if [ -f /opt/ros/noetic/setup.bash ]; then
  source /opt/ros/noetic/setup.bash
fi

# 启动 algo_bridge（前台）
python3 -m algo_bridge.main
