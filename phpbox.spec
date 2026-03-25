# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

block_cipher = None

# 项目根目录
project_root = Path(SPECPATH)

pyqt6_datas = []
for subdir in (
    "Qt6/plugins/platforms",
    "Qt6/plugins/wayland-decoration-client",
    "Qt6/plugins/wayland-graphics-integration-client",
):
    pyqt6_datas.extend(collect_data_files("PyQt6", subdir=subdir))

pyqt6_binaries = collect_dynamic_libs("PyQt6")

a = Analysis(
    ['main.py'],
    pathex=[str(project_root)],
    binaries=pyqt6_binaries,
    datas=[
        # 资源文件
        ('resources', 'resources'),
        *pyqt6_datas,
    ],
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.sip',
        'PyQt6.QtDBus',
        'qfluentwidgets',
        'qfluentwidgets.common',
        'qfluentwidgets.components',
        'qfluentwidgets.components.widgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyinstaller_rth_qt.py'],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'PIL',
        'scipy',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='phpbox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可以设置图标: 'resources/icons/app.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='phpbox',
)

# Linux desktop 文件安装 (可选)
# 如果需要创建 desktop entry，可以在打包后手动创建
