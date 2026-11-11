# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：python -m PyInstaller UAVSA.spec
import sys
from pathlib import Path

repo = Path(SPECPATH).parent.parent          # UAVSA-v1.0/
gui = Path(SPECPATH)                          # UAVSA-v1.0/gui/

a = Analysis(
    [str(gui / "main.py")],
    pathex=[str(repo / "docker1"), str(gui)],
    binaries=[],
    datas=[(str(gui / "index.html"), ".")],
    hiddenimports=[
        "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
        "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan", "uvicorn.lifespan.on",
        "agent", "agent.main", "agent.config", "agent.llm", "agent.loop", "agent.memory",
        "agent.backends", "agent.backends.mock", "agent.backends.http", "agent.backends.base",
        "agent.tools", "agent.tools.builder", "agent.tools.registry",
        "agent.tools.knowledge", "agent.tools.time_series", "agent.tools.report",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="UAVSA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # GUI 程序，无控制台
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
