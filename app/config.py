# ===============================================================
# 文件: config.py
# 项目: 健康数据监控（health-monitor）
# 说明: 环境变量配置（存储/上传限制/品牌/登录/LLM 超时）
# ===============================================================
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEFAULT_DATABASE_URL = f"sqlite+aiosqlite:///{(BASE_DIR / 'data' / 'health.db').as_posix()}"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # 存储
    database_url: str = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    data_dir: str = os.getenv("DATA_DIR", str(BASE_DIR / "data"))

    # 图片上传：单文件大小上限 / OCR 文本长度上限 / 原件保存目录
    max_upload_size_mb: int = _env_int("MAX_UPLOAD_SIZE_MB", 20)
    max_ocr_text_length: int = _env_int("MAX_OCR_TEXT_LENGTH", 500000)
    uploads_dir: str = os.getenv("UPLOADS_DIR", str(Path(data_dir) / "uploads"))

    # LLM 调用通用超时（模型由「模型设置」页自定义模型提供，不走 .env 配置）
    llm_timeout: float = _env_float("DEEPSEEK_TIMEOUT", 60.0)

    # 品牌与登录：配置 AUTH_PASSWORD 即开启登录
    site_title: str = os.getenv("SITE_TITLE", "健康数据监控")
    site_tagline: str = os.getenv("SITE_TAGLINE", "个人体检与病历数据管理")
    auth_username: str = os.getenv("AUTH_USERNAME", "admin")
    auth_password: str = os.getenv("AUTH_PASSWORD", "")
    auth_secret: str = os.getenv("AUTH_SECRET", "") or os.getenv("AUTH_PASSWORD", "")
    session_ttl_hours: int = _env_int("SESSION_TTL_HOURS", 24 * 7)

    @property
    def auth_enabled(self) -> bool:
        """登录开关：配置了 AUTH_PASSWORD 即开启（用户名默认 admin）。"""
        return bool(self.auth_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()