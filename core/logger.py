"""日志模块"""
import logging
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime


def _resolve_log_dir() -> Path:
    """解析可写日志目录，优先用户目录，失败时回退到临时目录"""
    candidates = []

    env_dir = os.environ.get("PHPBOX_LOG_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())

    candidates.append(Path.home() / ".phpbox" / "logs")
    candidates.append(Path(tempfile.gettempdir()) / "phpbox-logs")

    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / ".write-test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            return path
        except Exception:
            continue

    # 理论上的最后回退
    return Path(tempfile.gettempdir())


def setup_logger(name: str = "phpbox") -> logging.Logger:
    """设置日志记录器"""
    # 日志目录
    log_dir = _resolve_log_dir()

    # 日志文件名（按日期）
    log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"

    # 创建 logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # 避免重复添加 handler
    if not logger.handlers:
        # 文件处理器
        file_handler = logging.FileHandler(
            log_file,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)

        # 控制台处理器（开发模式）
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)

        # 格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # 添加处理器
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


# 全局 logger 实例
logger = setup_logger()
