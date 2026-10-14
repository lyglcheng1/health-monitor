from collections.abc import AsyncGenerator

import pytest

# 测试必须与本地 .env 解耦：load_dotenv 不会覆盖已存在的环境变量，所以在导入
# app 之前显式钉死登录开关——否则本机 .env 里配置的 AUTH_PASSWORD 会让未带
# 凭据的请求全部 401（登录开启态），套件随 .env 变红。
import os

os.environ.setdefault("AUTH_PASSWORD", "")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import setup_engine
from app.models import Base


@pytest_asyncio.fixture
async def engine(tmp_path) -> AsyncGenerator[AsyncEngine, None]:
    """每个测试一个独立临时库文件，function 级避免事件循环/内存库共享问题。"""
    db_file = tmp_path / "test_health.db"
    eng, _ = setup_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """每个测试一个独立事务，测完回滚。"""
    conn = await engine.connect()
    trans = await conn.begin()
    maker = async_sessionmaker(conn, expire_on_commit=False)
    async with maker() as s:
        yield s
    await trans.rollback()
    await conn.close()


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """用临时库引擎替换默认引擎的 HTTP 客户端。"""
    import app.db as db_module
    from app.main import app

    old_engine = db_module.engine
    db_module.engine = engine
    db_module.SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # teardown：还原引擎
    db_module.engine = old_engine