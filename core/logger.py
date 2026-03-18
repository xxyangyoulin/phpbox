"""日志模块"""
import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logger(name: str = "phpbox") -> logging.Logger:
    """设置日志记录器"""
    # 日志目录
    log_dir = Path.home() / ".phpbox" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

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
