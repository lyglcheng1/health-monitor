# ===============================================================
# 文件: db.py
# 项目: 健康数据监控（health-monitor）
# 说明: 建表 + 幂等补列迁移
# ===============================================================
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app import models
from app.config import get_settings

settings = get_settings()


def _set_sqlite_pragma(dbapi_conn, _record) -> None:
    """每个 SQLite 连接开启外键约束，保证级联删除生效。"""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


engine: AsyncEngine = create_async_engine(settings.database_url, echo=False)
event.listen(engine.sync_engine, "connect", _set_sqlite_pragma)
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


def setup_engine(url: str | None = None) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """按需创建独立引擎（测试用临时库），带外键 PRAGMA。"""
    url = url or settings.database_url
    eng = create_async_engine(url, echo=False)
    event.listen(eng.sync_engine, "connect", _set_sqlite_pragma)
    maker = async_sessionmaker(eng, expire_on_commit=False)
    return eng, maker


async def init_db(engine: AsyncEngine) -> None:
    """建 data 目录 + 业务表；对存量库幂等补列（后续版本加列场景）。"""
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
        # 存量 model_settings 表补列（新库由 create_all 一次建齐）
        res = await conn.execute(text("PRAGMA table_info(model_settings)"))
        ms_cols = {row[1] for row in res.fetchall()}
        if "kind" not in ms_cols:
            await conn.execute(text("ALTER TABLE model_settings ADD COLUMN kind VARCHAR(10) NOT NULL DEFAULT 'env'"))
        if "base_url" not in ms_cols:
            await conn.execute(text("ALTER TABLE model_settings ADD COLUMN base_url VARCHAR(500) NOT NULL DEFAULT ''"))
        if "api_key" not in ms_cols:
            await conn.execute(text("ALTER TABLE model_settings ADD COLUMN api_key VARCHAR(300) NOT NULL DEFAULT ''"))
        if "protocol" not in ms_cols:
            await conn.execute(text("ALTER TABLE model_settings ADD COLUMN protocol VARCHAR(10) NOT NULL DEFAULT 'openai'"))

        # 存量 exams 表补「来源/附件名称」列，并一次性从 note「来源：xxx」回填
        res = await conn.execute(text("PRAGMA table_info(exams)"))
        ex_cols = {row[1] for row in res.fetchall()}
        if "source" not in ex_cols:
            await conn.execute(text("ALTER TABLE exams ADD COLUMN source VARCHAR(500) NOT NULL DEFAULT ''"))
            await conn.execute(
                text("UPDATE exams SET source = substr(note, 4) WHERE source = '' AND note LIKE '来源：%'")
            )


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session