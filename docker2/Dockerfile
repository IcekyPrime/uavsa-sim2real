# ============================================================
# docker2：被测算法（EGO-Planner，ROS1 Noetic / Ubuntu 20.04）
# ============================================================
# Docker Hub 直连受限，使用 daocloud 镜像源
FROM docker.m.daocloud.io/library/ubuntu:20.04

ARG DEBIAN_FRONTEND=noninteractive

# ---------- 1. 基础工具 ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
        locales curl gnupg lsb-release software-properties-common wget \
        python3 python3-pip git build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

# ---------- 2. ROS Noetic ----------
RUN locale-gen en_US en_US.UTF-8 && update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
ENV LANG=en_US.UTF-8
RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
      -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] https://mirrors.tuna.tsinghua.edu.cn/ros/ubuntu focal main" \
      > /etc/apt/sources.list.d/ros1.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
         ros-noetic-desktop-full python3-rosdep python3-rosinstall python3-rosinstall-generator \
         python3-wstool python3-catkin-tools \
         libeigen3-dev libpcl-dev \
    && rm -rf /var/lib/apt/lists/*

# ---------- 3. Python 依赖（algo_bridge） ----------
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# ---------- 4. EGO-Planner 源码 ----------
# 说明：EGO-Planner 官方仿真依赖 uav_simulator(Gazebo classic)+PX4，较重。
# v1.0 仅克隆 planner 本体；GitHub 直连受限，经 ghfast.top 代理克隆。
RUN git clone --depth 1 https://ghfast.top/https://github.com/ZJU-FAST-Lab/ego-planner.git /workspace/ego-planner

# ---------- 5. 应用代码 ----------
COPY docker2/algo_bridge /workspace/algo_bridge
COPY docker2/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace
ENTRYPOINT ["/entrypoint.sh"]
