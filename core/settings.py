"""设置管理模块"""
from PyQt6.QtCore import QSettings
from typing import Optional


class Settings:
    """应用设置管理"""

    def __init__(self):
        self.settings = QSettings("PHPDev", "phpbox")

    def get_proxy(self) -> Optional[str]:
        """获取代理设置"""
        enabled = self.settings.value("proxy/enabled", False, type=bool)
        if not enabled:
            return None
        host = self.settings.value("proxy/host", "", type=str)
        port = self.settings.value("proxy/port", "", type=str)
        if host and port:
            return f"http://{host}:{port}"
        return None

    def set_proxy(self, host: str, port: str, enabled: bool):
        """设置代理"""
        self.settings.setValue("proxy/host", host)
        self.settings.setValue("proxy/port", port)
        self.settings.setValue("proxy/enabled", enabled)

    def is_proxy_enabled(self) -> bool:
        """代理是否启用"""
        return self.settings.value("proxy/enabled", False, type=bool)

    def get_proxy_host(self) -> str:
        """获取代理主机"""
        return self.settings.value("proxy/host", "127.0.0.1", type=str)

    def get_proxy_port(self) -> str:
        """获取代理端口"""
        return self.settings.value("proxy/port", "7890", type=str)

    def get_theme(self) -> str:
        """获取主题设置"""
        return self.settings.value("theme", "auto", type=str)

    def set_theme(self, theme: str):
        """设置主题"""
        self.settings.setValue("theme", theme)
