"""配置管理模块"""
import os
from pathlib import Path

# 基础目录
BASE_DIR = Path.home() / "php-dev" / "projects"

# PHP 版本列表
PHP_VERSIONS = ["8.4", "8.3", "8.2", "8.1", "8.0", "7.4", "7.3", "7.2"]

# 默认端口
DEFAULT_PORT = 8080

# 扩展分类定义
EXTENSIONS = {
    "数据库": [
        {"id": "pdo_mysql", "name": "MySQL PDO", "default": True},
        {"id": "mysqli", "name": "MySQL MySQLi", "default": False},
        {"id": "pdo_pgsql", "name": "PostgreSQL PDO", "default": False},
        {"id": "pdo_sqlite", "name": "SQLite PDO", "default": False},
        {"id": "pdo_dblib", "name": "MSSQL/Sybase PDO", "default": False},
        {"id": "mongodb", "name": "MongoDB", "default": False},
    ],
    "缓存/队列": [
        {"id": "redis", "name": "Redis", "default": True},
        {"id": "memcached", "name": "Memcached", "default": False},
        {"id": "apcu", "name": "APCu 本地缓存", "default": False},
        {"id": "amqp", "name": "RabbitMQ", "default": False},
    ],
    "图像处理": [
        {"id": "gd", "name": "GD 图像", "default": True},
        {"id": "imagick", "name": "ImageMagick", "default": False},
        {"id": "exif", "name": "EXIF 读取", "default": False},
        {"id": "vips", "name": "高性能图像", "default": False},
    ],
    "字符串/文本": [
        {"id": "mbstring", "name": "多字节字符串", "default": True},
        {"id": "intl", "name": "国际化", "default": False},
        {"id": "gettext", "name": "本地化翻译", "default": False},
        {"id": "iconv", "name": "字符编码转换", "default": True},
        {"id": "tidy", "name": "HTML 清理", "default": False},
    ],
    "数学/加密": [
        {"id": "bcmath", "name": "高精度数学", "default": True},
        {"id": "gmp", "name": "大数运算", "default": False},
        {"id": "sodium", "name": "现代加密", "default": False},
    ],
    "文件/压缩": [
        {"id": "zip", "name": "ZIP", "default": True},
        {"id": "bz2", "name": "BZ2 压缩", "default": False},
        {"id": "zstd", "name": "Zstd 压缩", "default": False},
        {"id": "lzf", "name": "LZF 压缩", "default": False},
    ],
    "网络/协议": [
        {"id": "curl", "name": "cURL", "default": True},
        {"id": "soap", "name": "SOAP", "default": False},
        {"id": "sockets", "name": "Sockets", "default": False},
        {"id": "ssh2", "name": "SSH2", "default": False},
        {"id": "imap", "name": "IMAP 邮件", "default": False},
        {"id": "ldap", "name": "LDAP 目录服务", "default": False},
        {"id": "snmp", "name": "SNMP 网络管理", "default": False},
        {"id": "xmlrpc", "name": "XML-RPC", "default": False},
    ],
    "XML/数据": [
        {"id": "xsl", "name": "XSL 转换", "default": False},
        {"id": "xmlwriter", "name": "XML 写入", "default": True},
        {"id": "simplexml", "name": "SimpleXML", "default": True},
        {"id": "dom", "name": "DOM 操作", "default": True},
        {"id": "xml", "name": "XML 基础", "default": True},
        {"id": "xmlreader", "name": "XML 读取", "default": True},
    ],
    "系统工具": [
        {"id": "tokenizer", "name": "Tokenizer", "default": True},
        {"id": "ctype", "name": "Ctype 字符检测", "default": True},
        {"id": "fileinfo", "name": "文件信息检测", "default": True},
        {"id": "phar", "name": "Phar 打包", "default": True},
    ],
    "序列化": [
        {"id": "igbinary", "name": "高效序列化", "default": True},
        {"id": "msgpack", "name": "MessagePack 序列化", "default": False},
    ],
    "进程/系统": [
        {"id": "pcntl", "name": "进程控制", "default": False},
        {"id": "shmop", "name": "共享内存", "default": False},
        {"id": "ffi", "name": "外部函数接口 (PHP>=7.4)", "default": False},
    ],
    "性能/调试": [
        {"id": "opcache", "name": "OPcache 加速", "default": False},
        {"id": "xdebug", "name": "Xdebug 调试", "default": False},
        {"id": "pcov", "name": "代码覆盖率", "default": False},
    ],
    "协程/高性能": [
        {"id": "swoole", "name": "Swoole 协程", "default": False},
        {"id": "openswoole", "name": "OpenSwoole 协程", "default": False},
    ],
    "RPC/消息": [
        {"id": "grpc", "name": "gRPC", "default": False},
        {"id": "protobuf", "name": "Protocol Buffers", "default": False},
    ],
    "其他": [
        {"id": "xlswriter", "name": "Excel 写入", "default": False},
        {"id": "yaml", "name": "YAML 解析", "default": False},
        {"id": "uuid", "name": "UUID 生成", "default": False},
        {"id": "rdkafka", "name": "Kafka 客户端", "default": False},
        {"id": "raphf", "name": "资源持久化句柄", "default": False},
        {"id": "http", "name": "HTTP 扩展 (依赖raphf)", "default": False},
        {"id": "dba", "name": "数据库抽象层", "default": False},
        {"id": "enchant", "name": "拼写检查", "default": False},
    ],
}

# 扩展版本兼容性 (PHP 版本 => 扩展版本)
EXT_VERSION_PHP72 = {
    "igbinary": "igbinary-^3.2",
    "xdebug": "xdebug-^3.1",
    "redis": "redis-^5.3",
    "swoole": "swoole-^4.8",
    "grpc": "grpc-^1.54",
    "protobuf": "protobuf-^3.25",
}

EXT_VERSION_PHP74 = {
    "igbinary": "igbinary-^3.2",
    "xdebug": "xdebug-^3.3",
    "redis": "redis-^6.0",
    "swoole": "swoole-^5.0",
}

EXT_VERSION_PHP83 = {
    "igbinary": "igbinary-^3.2",
    "redis": "redis-^6.0",
    "xdebug": "xdebug-^3.3",
}


def ensure_base_dir():
    """确保基础目录存在"""
    BASE_DIR.mkdir(parents=True, exist_ok=True)
