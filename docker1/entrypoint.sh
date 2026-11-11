#!/usr/bin/env bash
set -e

echo "[docker1] entrypoint: starting sim_bridge + agent"

# source ROS2（若已安装）
if [ -f /opt/ros/jazzy/setup.bash ]; then
  source /opt/ros/jazzy/setup.bash || true
fi

# 启动 sim_bridge（后台）
python3 -m sim_bridge.main &
SIM_PID=$!

# 启动 agent（前台）
python3 -m agent.main --docker

# 若 agent 退出，清理 sim_bridge
kill $SIM_PID 2>/dev/null || true
