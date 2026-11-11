# ============================================================
# docker1：仿真平台（Gazebo Harmonic + PX4 SITL）+ Agent + sim_bridge
# 基座 Ubuntu 24.04，对应 WSL 侧的 ROS2 Jazzy / Gazebo Harmonic 版本
# ============================================================
# Docker Hub 直连受限，使用 daocloud 镜像源
FROM docker.m.daocloud.io/library/ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
# 是否在镜像内编译 PX4 SITL（非常耗时、占磁盘，默认跳过，运行时用脚本编译/挂载）
ARG BUILD_PX4=0

# ---------- 1. 基础工具 ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
        locales curl gnupg lsb-release software-properties-common wget \
        python3 python3-pip python3-venv git build-essential cmake \
        xauth x11-apps \
    && rm -rf /var/lib/apt/lists/*

# ---------- 2. 设置 locale ----------
RUN locale-gen en_US en_US.UTF-8 && update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
ENV LANG=en_US.UTF-8

# ---------- 3. ROS2 Jazzy + Gazebo Harmonic ----------
# gz-harmonic 来自 OSRF 仓库，需单独添加（ROS2 仓库不包含它）
RUN add-apt-repository universe \
    && curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
         -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu noble main" \
         > /etc/apt/sources.list.d/ros2.list \
    && curl -sSL https://packages.osrfoundation.org/gazebo.gpg \
         -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable noble main" \
         > /etc/apt/sources.list.d/gazebo-stable.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
         ros-jazzy-desktop ros-dev-tools python3-rosdep \
         gz-harmonic \
    && rm -rf /var/lib/apt/lists/*

# ---------- 4. Python 依赖 ----------
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# ---------- 5. PX4-Autopilot 源码（浅克隆；编译需 --build-arg BUILD_PX4=1） ----------
# GitHub 直连受限，经 ghfast.top 代理克隆
RUN git clone --depth 1 https://ghfast.top/https://github.com/PX4/PX4-Autopilot.git /src/PX4-Autopilot
# 可选：镜像内编译 PX4 SITL（gz_x500）
RUN if [ "$BUILD_PX4" = "1" ]; then \
        cd /src/PX4-Autopilot && bash ./Tools/setup/ubuntu.sh && make px4_sitl gz_x500; \
    fi

# ---------- 6. 应用代码 ----------
COPY docker1/sim_bridge /workspace/sim_bridge
COPY docker1/agent /workspace/agent
COPY docker1/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace
ENTRYPOINT ["/entrypoint.sh"]
