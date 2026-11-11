# -*- coding: utf-8 -*-
"""集群 SSH 客户端：穿越 JumpServer 堡垒机登录节点并执行命令。

用法：
    from .cluster_ssh import ClusterSSH
    c = ClusterSSH()
    c.connect()
    out = c.run("docker ps -a")
    c.close()

实现要点：
  - 入口是 JumpServer 堡垒机（交互式菜单 Opt>），需输入节点名 + 回车(\\r)进入目标机 shell。
  - 命令执行用「行首锚定的随机标记」包裹：echo BEGIN; <cmd>; echo END，
    只截取 BEGIN 与 END 两个独立输出行之间的内容，天然规避回显与提示符串扰。
"""
from __future__ import annotations

import os
import random
import re
import socket
import string
import sys
import time
from typing import Optional

# 可选的本地依赖目录（把 paramiko 放在本文件同级 deps/ 下时优先加载）
_DEPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deps")
if os.path.isdir(_DEPS) and _DEPS not in sys.path:
    sys.path.insert(0, _DEPS)

import paramiko

# 集群连接参数全部来自环境变量，仓库内不保存任何主机、账号或口令。
# 参考 .env.example 中的 CLUSTER_SSH_* 配置。
DEFAULTS = {
    "host": os.environ.get("CLUSTER_SSH_HOST", ""),
    "port": int(os.environ.get("CLUSTER_SSH_PORT", "22") or 22),
    "user": os.environ.get("CLUSTER_SSH_USER", ""),
    "password": os.environ.get("CLUSTER_SSH_PASSWORD", ""),
    "node": os.environ.get("CLUSTER_SSH_NODE", ""),
}


class ClusterSSH:
    def __init__(
        self,
        host: str = DEFAULTS["host"],
        port: int = DEFAULTS["port"],
        user: str = DEFAULTS["user"],
        password: str = DEFAULTS["password"],
        node: str = DEFAULTS["node"],
        width: int = 220,
        height: int = 50,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.node = node
        self.width = width
        self.height = height
        self._cli: Optional[paramiko.SSHClient] = None
        self._shell = None

    # ---------- 连接 ----------
    def connect(self, login_timeout: float = 30.0) -> "ClusterSSH":
        missing = [k for k in ("host", "user", "password", "node") if not getattr(self, k)]
        if missing:
            raise RuntimeError(
                "未配置集群 SSH，缺少：" + ", ".join("CLUSTER_SSH_" + m.upper() for m in missing)
                + "。请在 .env 中填写后重试（参考 .env.example）。"
            )
        self._cli = paramiko.SSHClient()
        self._cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._cli.connect(
            self.host, port=self.port, username=self.user, password=self.password,
            timeout=login_timeout, look_for_keys=False, allow_agent=False,
        )
        self._shell = self._cli.invoke_shell(width=self.width, height=self.height)
        self._shell.settimeout(0.4)  # 避免 recv 无限阻塞
        self._wait_for("Opt>", timeout=15.0, desc="堡垒机菜单")
        self._shell.send(self.node + "\r")
        time.sleep(4.0)          # 等待登录完成
        self._drain(1.0)
        if "__READY__" not in self.run("echo __READY__"):
            raise RuntimeError("登录后 shell 未就绪")
        return self

    # ---------- 命令执行 ----------
    def run(self, cmd: str, read_timeout: float = 60.0) -> str:
        """执行一条命令，返回 BEGIN/END 标记之间的干净 stdout。"""
        if self._shell is None:
            raise RuntimeError("未连接，请先调用 connect()")
        self._drain(0.3)
        token = "".join(random.choices(string.ascii_letters, k=14))
        begin, end = "B_" + token, "E_" + token
        self._shell.send(f"echo {begin}; {cmd}; echo {end}\r")
        raw = self._read_until_line(end, read_timeout)
        # 稳健提取：取最后一次出现的 begin（真实 echo 输出）到其后首个 end 之间的内容，
        # 规避终端回显命令本身带来的干扰，也不受 CR/LF 混用影响。
        b = raw.rfind(begin)
        e = raw.find(end, b + len(begin)) if b != -1 else -1
        if b != -1 and e != -1:
            return raw[b + len(begin):e].strip("\r\n \t")
        return raw.strip()

    # ---------- 集群 docker 编排（本用户容器） ----------
    def container_id(self, name_part: str, running_only: bool = False) -> str:
        """返回本用户（ai_<user>_ 前缀）容器中，名字包含 name_part 的容器 ID。"""
        state = "" if running_only else " -a"
        cmd = (
            f"docker ps{state} --format '{{{{.ID}}}}|{{{{.Names}}}}' "
            f"| grep 'ai_{self.user}_' | grep -F '{name_part}' | head -1 | cut -d'|' -f1"
        )
        out = self.run(cmd, read_timeout=30).strip()
        return out.splitlines()[0].strip() if out else ""

    def docker_exec(self, name_part: str, inner_cmd: str, read_timeout: float = 60.0) -> str:
        """在本用户容器（名字含 name_part）内执行命令，自动解析容器 ID。"""
        cid = self.container_id(name_part)
        if not cid:
            return f"[未找到容器：ai_{self.user}_*{name_part}*]"
        return self.run(f"docker exec {cid} bash -lc '{inner_cmd}'", read_timeout=read_timeout)

    # ---------- 底层读取 ----------
    def _read_until_line(self, needle: str, timeout: float) -> str:
        """读取直到 needle 作为独立一行（行首）出现。"""
        self._shell.settimeout(0.4)
        buf = b""
        rx = re.compile(rb"(?:\r?\n)" + needle.encode("utf-8"))
        start = time.time()
        while time.time() - start < timeout:
            try:
                chunk = self._shell.recv(65535)
            except (socket.timeout, paramiko.buffered_pipe.PipeTimeout):
                chunk = b""
            if chunk:
                buf += chunk
                if rx.search(buf):
                    break
            else:
                time.sleep(0.03)
        return buf.decode("utf-8", "replace")

    def _wait_for(self, needle: str, timeout: float, desc: str = ""):
        self._shell.settimeout(0.4)
        buf = b""
        nb = needle.encode("utf-8")
        start = time.time()
        while time.time() - start < timeout:
            try:
                chunk = self._shell.recv(65535)
            except (socket.timeout, paramiko.buffered_pipe.PipeTimeout):
                chunk = b""
            if chunk:
                buf += chunk
                if nb in buf:
                    return
            else:
                time.sleep(0.03)
        raise TimeoutError(f"等待「{desc}」超时（{timeout}s）")

    def _drain(self, timeout: float):
        self._shell.settimeout(0.4)
        start = time.time()
        while time.time() - start < timeout:
            try:
                self._shell.recv(65535)
            except (socket.timeout, paramiko.buffered_pipe.PipeTimeout):
                time.sleep(0.03)

    def close(self):
        try:
            if self._shell is not None:
                self._shell.close()
        except Exception:
            pass
        try:
            if self._cli is not None:
                self._cli.close()
        except Exception:
            pass
