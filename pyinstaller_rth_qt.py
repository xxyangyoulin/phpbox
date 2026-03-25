import os
import sys
from pathlib import Path


if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    qt_root = Path(sys._MEIPASS) / "PyQt6" / "Qt6"
    plugin_dir = qt_root / "plugins"
    platform_plugin_dir = plugin_dir / "platforms"
    qml_dir = qt_root / "qml"
    lib_dir = qt_root / "lib"

    if plugin_dir.is_dir():
        os.environ["QT_PLUGIN_PATH"] = str(plugin_dir)
    if platform_plugin_dir.is_dir():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platform_plugin_dir)
    if qml_dir.is_dir():
        os.environ["QML2_IMPORT_PATH"] = str(qml_dir)
    if lib_dir.is_dir():
        current = os.environ.get("LD_LIBRARY_PATH")
        os.environ["LD_LIBRARY_PATH"] = (
            f"{lib_dir}:{current}" if current else str(lib_dir)
        )
