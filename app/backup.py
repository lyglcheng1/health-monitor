# ===============================================================
# 文件: backup.py
# 项目: 健康数据监控（health-monitor）
# 说明: 打包 health.db + uploads/ + manifest.json，还原时换库并重绑引擎
# ===============================================================
"""备份还原：全量数据打包 / 清单 / 上传 / 还原 / 删除。

打包内容：
- health.db：SQLite backup API 在线快照（不阻塞应用写入，不带 -wal 旁文件）
- uploads/：体检图片原件
- manifest.json：版本/时间/主机/行数统计（还原前校验，非本应用包直接拒绝）
不含：data/backups/ 自身（防递归）、.env、代码。

还原（先 safety 快照 → staging 就绪 → 文件换位 → 重绑 → 失败逆序回滚）：
1. 解包到 data/.restore-* 临时区并校验（成员白名单，防路径穿越/防超大展开）
2. 当前数据先打包成 safety_*.tar.gz（还原失败也能从备份列表下载救回）
3. 包内 kb.db 用 init_db 就地升级 schema（旧版本备份可直还原到新版本代码）
4. 文件换位进 data/（旧 db 改名留底 data/restore_<ts>.db，不自动删）
5. 重绑：db_module.engine/SessionLocal 换新 → 重载自定义模型注册表 → 清池
6. 任一环节异常：逆序恢复已换位文件并 re-raise

跨机迁移：源机「下载」tar.gz（或 scp 进目标机 data/backups/），目标机上传/还原。
LAN 单用户：模块级非阻塞锁保证同一时刻仅一个备份/还原。
异常约定：BackupBusy=1008/409、损坏包 ValueError=1007/400、
FileNotFoundError=2005/404、其余 OSError 等 =3004/500。
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import platform
import re
import shutil
import sqlite3
import tarfile
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

# 备份文件名白名单：kb_*/safety_* + [0-9A-Za-z._-]（≤120 字符）+ .tar.gz。
_NAME_RE = re.compile(r"^(?:kb|safety)_[0-9A-Za-z._-]{1,120}\.tar\.gz$")
_MANIFEST = "manifest.json"
_SAFE_STEM = re.compile(r"[^0-9A-Za-z._-]")
_MAX_EXTRACT_BYTES = 2 * 1024 * 1024 * 1024  # 解包展开总大小上限 2GB（防压缩炸弹）

# 同进程互斥（还原中途再点还原必坏，直接拒；LAN 单用户足够）
_op_lock = threading.Lock()


class BackupBusy(RuntimeError):
    """另一项备份/还原正在进行。"""


def safe_name(name: str) -> bool:
    return bool(_NAME_RE.match(name or ""))


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _paths() -> dict[str, Path]:
    """数据面路径集合。测试通过 _paths_override 注入临时目录。"""
    if _paths_override is not None:
        return dict(_paths_override)
    s = get_settings()
    data = Path(s.data_dir)
    url = s.database_url
    if url.startswith("sqlite+aiosqlite:///"):
        db = Path(url[len("sqlite+aiosqlite:///"):])
    else:  # 内存库/其他后端：回落 data/health.db（备份功能要求文件库）
        db = data / "health.db"
    return {
        "data": data,
        "db": db,
        "uploads": Path(s.uploads_dir),
        "backups": data / "backups",
    }


# 测试注入点：{"data","db","uploads","backups"} → Path
_paths_override: dict[str, Path] | None = None


def _acquire() -> None:
    if not _op_lock.acquire(blocking=False):
        raise BackupBusy("另一项备份/还原正在进行，请稍后再试")


def _counts_from(conn: sqlite3.Connection) -> dict:
    out: dict[str, int] = {}
    for table, key in (
        ("exams", "exams"),
        ("metrics", "metrics"),
        ("body_records", "body_records"),
        ("model_settings", "models"),
    ):
        try:
            out[key] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error:  # 旧库缺表：计 0，不算损坏
            out[key] = 0
    return out


def _db_snapshot(dst_path: Path) -> dict:
    """当前 health.db 的一致性在线快照（sqlite3 backup API，走 SQLite 自身锁）。"""
    src_file = _paths()["db"]
    if not src_file.is_file():
        raise FileNotFoundError("数据库文件不存在（应用未完成首次初始化）")
    src = sqlite3.connect(str(src_file), timeout=5.0)
    try:
        dst = sqlite3.connect(str(dst_path))
        try:
            with dst:
                src.backup(dst)
            return _counts_from(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _add_tree(tar: tarfile.TarFile, arc: str, base: Path) -> int:
    """整目录入包，返回文件数（空/缺目录记 0）。"""
    if not base.is_dir():
        return 0
    n = 0
    for p in sorted(base.rglob("*")):
        if p.is_file():
            tar.add(str(p), arcname=f"{arc}/{p.relative_to(base).as_posix()}")
            n += 1
    return n


# ── 打包 ──


def _do_backup(label: str, kind: str = "kb") -> dict:
    """打包当前数据到 data/backups/<kind>_<ts>[_label].tar.gz。调用方须已持锁。"""
    p = _paths()
    p["backups"].mkdir(parents=True, exist_ok=True)
    ts = _utc_stamp()
    slug = _SAFE_STEM.sub("", (label or "").strip())[:32]
    slug = re.sub(r"\.{2,}", ".", slug).strip(".")
    filename = f"{kind}_{ts}_{slug}.tar.gz" if slug else f"{kind}_{ts}.tar.gz"
    dest = p["backups"] / filename
    fd, tmp_name = tempfile.mkstemp(dir=str(p["backups"]), suffix=".tar.gz.part")
    os.close(fd)
    tmp = Path(tmp_name)
    snap_fd, snap_name = tempfile.mkstemp(suffix=".health.db")
    os.close(snap_fd)
    snap = Path(snap_name)
    try:
        counts = _db_snapshot(snap)
        with tarfile.open(tmp, "w:gz") as tar:
            tar.add(str(snap), arcname="health.db")
            n_up = _add_tree(tar, "uploads", p["uploads"])
            manifest = {
                "app": "health-monitor",
                "version": 1,
                "created_at": ts,
                "hostname": platform.node(),
                "label": slug,
                "counts": counts,
                "upload_files": n_up,
            }
            data = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            info = tarfile.TarInfo(_MANIFEST)
            info.size = len(data)
            info.mtime = int(datetime.now(timezone.utc).timestamp())
            tar.addfile(info, io.BytesIO(data))
        tmp.replace(dest)
        logger.info("备份完成 %s（exams=%s，原件=%d）",
                    filename, counts.get("exams"), n_up)
        return {"filename": filename, "size_bytes": dest.stat().st_size,
                "created_at": ts, "counts": counts}
    finally:
        tmp.unlink(missing_ok=True)
        snap.unlink(missing_ok=True)


def create_backup(label: str = "") -> dict:
    """全量备份当前数据，返回 {filename,size_bytes,created_at,counts}。"""
    _acquire()
    try:
        return _do_backup(label)
    finally:
        _op_lock.release()


# ── 清单 / 文件访问 ──


def list_backups() -> list[dict]:
    """data/backups/ 下合法命名的备份，新→旧（带 manifest 摘要；读不出的标 corrupt）。"""
    p = _paths()
    items: list[dict] = []
    if not p["backups"].is_dir():
        return items
    for f in sorted(p["backups"].iterdir(), reverse=True):
        if not (f.is_file() and safe_name(f.name)):
            continue
        item: dict[str, Any] = {
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "kind": "safety" if f.name.startswith("safety_") else "manual",
            "created_at": "",
            "counts": None,
            "corrupt": False,
        }
        try:
            with tarfile.open(f, "r:gz") as tar:
                m = tar.extractfile(_MANIFEST)
                if m is None:
                    raise ValueError("no manifest")
                mf = json.loads(m.read().decode("utf-8"))
                item["created_at"] = mf.get("created_at", "")
                item["counts"] = mf.get("counts")
                item["hostname"] = mf.get("hostname", "")
        except Exception:
            item["corrupt"] = True
        items.append(item)
    return items


def backup_file(name: str) -> Path | None:
    """解析备份文件路径（非法名/目录穿越/不存在 → None）。"""
    if not safe_name(name):
        return None
    p = _paths()
    backups = p["backups"].resolve()
    path = (backups / name).resolve()
    if path.parent != backups or not path.is_file():
        return None
    return path


def delete_backup(name: str) -> bool:
    _acquire()
    try:
        path = backup_file(name)
        if path is None:
            return False
        path.unlink(missing_ok=True)
        return True
    finally:
        _op_lock.release()


def save_upload(stream, filename: str) -> dict:
    """上传备份包入库（存为 kb_<ts>_upload-<stem>.tar.gz），先解包校验再落位。

    stream 为二进制可迭代对象（UploadFile.file）；校验失败抛 ValueError（不落盘）。
    """
    _acquire()
    try:
        p = _paths()
        p["backups"].mkdir(parents=True, exist_ok=True)
        stem = _SAFE_STEM.sub("", Path(filename or "").name.removesuffix(".tar.gz"))[:32]
        ts = _utc_stamp()
        final_name = f"kb_{ts}_upload-{stem or 'pkg'}.tar.gz"
        dest = p["backups"] / final_name
        fd, tmp_name = tempfile.mkstemp(dir=str(p["backups"]), suffix=".upload.part")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(stream, out)
            with tempfile.TemporaryDirectory(prefix="hm-vpkg-", dir=str(p["data"])) as vd:
                manifest = _verify_package(tmp, Path(vd))
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
        return {"filename": final_name, "size_bytes": dest.stat().st_size,
                "created_at": manifest.get("created_at", ts),
                "counts": manifest.get("counts")}
    finally:
        _op_lock.release()


# ── 还原 ──


def _verify_package(src: Path, workdir: Path) -> dict:
    """解包并校验：成员白名单（manifest.json/health.db/uploads/**），
    防路径穿越/特殊文件，展开总大小 ≤2GB。返回 manifest（校验 app 标识）。"""
    total = 0
    with tarfile.open(src, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name in (".", "./", ""):
                continue
            rel = Path(member.name.replace("\\", "/"))
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError(f"备份包含非法路径条目：{member.name}")
            if rel.parts[0] not in ("manifest.json", "health.db", "uploads"):
                raise ValueError(f"备份包含预期外条目：{member.name}")
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"备份包含特殊文件：{member.name}")
            if member.isfile():
                total += member.size
                if total > _MAX_EXTRACT_BYTES:
                    raise ValueError("备份展开体积超过 2GB 上限")
        tar.extractall(path=str(workdir))
    mf_file = workdir / _MANIFEST
    if not mf_file.is_file():
        raise ValueError("缺少 manifest.json，不是本应用的备份包")
    manifest = json.loads(mf_file.read_bytes().decode("utf-8"))
    if not isinstance(manifest, dict) or manifest.get("app") != "health-monitor":
        raise ValueError("manifest 校验失败（非 health-monitor 备份包）")
    if not (workdir / "health.db").is_file():
        raise ValueError("备份缺少 health.db")
    return manifest


async def _upgrade_db(db_path: Path) -> dict:
    """包内 health.db 就地升级到当前 schema + 行数统计。"""
    from app import db as db_module

    eng, _maker = db_module.setup_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    try:
        await db_module.init_db(eng)
        async with eng.connect() as conn:
            from sqlalchemy import text

            counts: dict[str, int] = {}
            for table, key in (
                ("exams", "exams"), ("metrics", "metrics"),
                ("body_records", "body_records"), ("model_settings", "models"),
            ):
                try:
                    counts[key] = (await conn.execute(
                        text(f"SELECT COUNT(*) FROM {table}")
                    )).scalar_one()
                except Exception:
                    counts[key] = 0
        return counts
    finally:
        await eng.dispose()


async def _finalize_rebind(db_module: Any, new_engine: Any, new_maker: Any) -> None:
    """文件换位完成后的进程内重绑（在同一个临时事件循环内跑完所有 DB 触碰）。

    1) 全局引用切到新引擎/会话工厂（此后所有模块经 db_module 取用）
    2) 重载自定义模型注册表（llm.set_custom_models，health.db 已换新）
    3) 新引擎 dispose 清池：aiosqlite 连接绑创建循环，清空后服务循环首用自动重连
    """
    import app.llm as llm_module
    from app import crud

    db_module.engine = new_engine
    db_module.SessionLocal = new_maker
    try:
        async with new_maker() as s:
            llm_module.set_custom_models(await crud.custom_models_map(s))
    finally:
        try:
            await new_engine.dispose()
        except Exception:
            logger.warning("还原收尾：临时引擎池释放失败（重启自愈）", exc_info=True)


def restore_backup(name: str) -> dict:
    """还原 data/backups/<name>.tar.gz。

    返回 {exams, metrics, body_records, models, safety}。
    任一环节失败：逆序回滚已换位文件并抛异常。
    调用约定：在无事件循环的线程中执行（HTTP 端点走 run_in_threadpool）。
    """
    _acquire()
    try:
        return _restore(name)
    finally:
        _op_lock.release()


def _restore(name: str) -> dict:
    import app.db as db_module

    p = _paths()
    src = backup_file(name)
    if src is None:
        raise FileNotFoundError(name)

    ts = _utc_stamp()
    work = Path(tempfile.mkdtemp(prefix=f".restore-{ts}-", dir=str(p["data"])))
    moves: list[tuple[Path, Path]] = []  # 换位登记 (现在的路径 → 原本的路径)
    old_engine = db_module.engine
    old_maker = db_module.SessionLocal
    new_engine = None
    swapped = False
    try:
        # 1) 解包 + 校验（非法包在此挡住，未动任何线上文件）
        manifest = _verify_package(src, work)
        new_db = work / "health.db"
        pkg_uploads = work / "uploads"

        # 2) safety 快照当前数据（还原失败也能从备份列表救回）
        safety = _do_backup("before-restore", kind="safety")

        # 3) 新库 schema 升级 + 统计
        counts = asyncio.run(_upgrade_db(new_db))

        # 4) 文件换位进 data/（旧库改名留底，不自动删；缺失项跳过）
        bak_db = p["data"] / f"restore_{ts}.db"
        if p["db"].exists():
            p["db"].rename(bak_db)
            moves.append((bak_db, p["db"]))
        new_db.rename(p["db"])
        moves.append((p["db"], new_db))
        swapped = True

        # uploads 并入：包内图片目录覆盖同名（包外原件保留=超集）
        if pkg_uploads.is_dir():
            p["uploads"].mkdir(parents=True, exist_ok=True)
            for item in sorted(pkg_uploads.iterdir()):
                if not item.is_dir():
                    continue
                try:
                    dst = p["uploads"] / item.name
                    if dst.exists():
                        shutil.rmtree(dst, ignore_errors=True)
                    item.replace(dst)
                except OSError:
                    logger.warning("上传图片目录并入失败（忽略）：%s", item.name,
                                   exc_info=True)

        # 5) 进程内重绑（单临时循环内完成，见 _finalize_rebind docstring）
        new_engine, new_maker = db_module.setup_engine(
            f"sqlite+aiosqlite:///{p['db'].as_posix()}"
        )
        asyncio.run(_finalize_rebind(db_module, new_engine, new_maker))
        new_engine = None  # 所有权已交 db_module

        logger.info("还原完成 %s：exams=%s，safety=%s；旧库留底 %s",
                    name, counts.get("exams"), safety["filename"], bak_db.name)
        return {
            "exams": counts.get("exams", 0),
            "metrics": counts.get("metrics", 0),
            "body_records": counts.get("body_records", 0),
            "models": counts.get("models", 0),
            "safety": safety["filename"],
        }
    except Exception:
        # 逆序回滚文件换位（半途失败恢复旧数据；回滚失败只记日志）
        for b, a in reversed(moves):
            try:
                if b.exists():
                    b.rename(a)
            except OSError:
                logger.exception("还原回滚失败：%s -> %s", b, a)
        if swapped:  # 重绑没跑成：恢复全局引用指向（文件已回滚=旧引擎仍有效）
            try:
                db_module.engine = old_engine
                db_module.SessionLocal = old_maker
            except Exception:
                logger.exception("还原回滚：引擎引用恢复失败（重启服务可恢复）")
        else:
            db_module.engine = old_engine
            db_module.SessionLocal = old_maker
        raise
    finally:
        if new_engine is not None:
            try:
                asyncio.run(new_engine.dispose())
            except Exception:
                pass
        shutil.rmtree(work, ignore_errors=True)