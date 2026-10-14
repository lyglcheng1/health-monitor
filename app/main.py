# ===============================================================
# 文件: main.py
# 项目: 健康数据监控（health-monitor）
# 说明: 体检记录（上传+OCR）、日常身体数据、模型管理（LLM 配置）、备份还原、登录会话
# ===============================================================
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth
from app import backup as backup_mod
from app.config import get_settings
from app.db import SessionLocal, engine, get_session, init_db
from app.schemas import (
    BackupCreate,
    BackupRestoreRequest,
    BodyRecordIn,
    CustomModelCreate,
    CustomModelUpdate,
    ExamDetailOut,
    ExamUpdate,
    LoginRequest,
    MetricIn,
)
from app import body3d, crud, llm, models, ocr

logger = logging.getLogger(__name__)
settings = get_settings()

# 单批最多上传图片数
MAX_UPLOAD_FILES = 10


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动时建表 + 加载自定义模型注册表。"""
    await init_db(engine)
    try:
        async with SessionLocal() as s:
            llm.set_custom_models(await crud.custom_models_map(s))
    except Exception:
        print("[startup] 自定义模型注册表加载跳过（数据库未就绪）")
    yield


app = FastAPI(title="健康数据监控", version="0.1.0", lifespan=lifespan)

# ── 请求体大小限制 ──
# 单文件 20MB 在接口内部校验（read 时截断）；这里按 Content-Length 拦请求总量
MAX_BODY_BYTES = 60 * 1024 * 1024


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
        return PlainTextResponse(status_code=413, content="request body too large")
    return await call_next(request)


# ── CSRF 防护（写操作 Origin/Host 校验）──
@app.middleware("http")
async def verify_origin(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("host", "")
            origin_host = urlsplit(origin).netloc.lower()
            if not host or origin_host != host.lower():
                return PlainTextResponse(status_code=403, content="cross-origin request blocked")
    return await call_next(request)


# ── 登录会话：.env 配置 AUTH_PASSWORD 即开启，未配置不拦截 ──
_AUTH_EXEMPT = re.compile(
    r"^/(?:login|api/(?:login|site-info|logout)|static/|demo-anatomy/|favicon\.ico|docs|openapi\.json)"
)


@app.middleware("http")
async def require_session(request: Request, call_next):
    if not settings.auth_enabled:
        return await call_next(request)
    path = request.url.path
    if _AUTH_EXEMPT.match(path):
        return await call_next(request)
    user = auth.read_token(request.cookies.get(auth.COOKIE_NAME))
    if user:
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse(
            status_code=401,
            content={"detail": {"code": 1001, "message": "未登录或会话已过期"}},
        )
    return RedirectResponse("/login", status_code=302)


@app.post("/api/login", response_model=dict)
async def api_login(body: LoginRequest, response: Response):
    """校验用户名口令，成功则签发签名会话 cookie。"""
    if not auth.verify_credentials(body.username, body.password):
        raise HTTPException(
            status_code=401,
            detail={"code": 1001, "message": "用户名或密码错误"},
        )
    token = auth.issue_token(body.username)
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"code": 0, "data": {"username": body.username}, "message": "登录成功"}


@app.post("/api/logout", response_model=dict)
async def api_logout(response: Response):
    """退出登录：清除会话 cookie。"""
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"code": 0, "data": None, "message": "已退出"}


@app.get("/api/site-info", response_model=dict)
async def api_site_info():
    """站点信息（公开，登录页与前端共用）：名称/副标题/登录开关。"""
    return {
        "code": 0,
        "data": {
            "title": settings.site_title,
            "tagline": settings.site_tagline,
            "auth_enabled": settings.auth_enabled,
        },
        "message": "成功",
    }


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── 3D 人体大屏资源（demo-anatomy 原样挂载，保留不改）──
DEMO_ANATOMY_DIR = Path(__file__).resolve().parent.parent / "demo-anatomy"
if DEMO_ANATOMY_DIR.is_dir():
    app.mount(
        "/demo-anatomy", StaticFiles(directory=str(DEMO_ANATOMY_DIR)), name="demo-anatomy"
    )


# ── V0.3 3D 人体大屏 ──
@app.get("/api/body3d/overview", response_model=dict)
async def api_body3d_overview(
    mode: str = "abnormal", session: AsyncSession = Depends(get_session)
):
    """3D 大屏数据：按身体部位聚合体检指标。

    mode=abnormal（默认）只返回存在异常的部位及其异常指标；
    mode=all 返回全部出现过指标的部位（正常部位 abnormal=false）。
    """
    if mode not in ("abnormal", "all"):
        raise HTTPException(
            status_code=400,
            detail={"code": 1002, "message": "mode 仅支持 abnormal|all"},
        )
    parts = await body3d.build_body3d_overview(session, mode=mode)
    return {"code": 0, "data": {"parts": parts}, "message": "成功"}


@app.get("/", response_class=FileResponse)
def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/login", response_class=FileResponse, include_in_schema=False)
def login_page():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/favicon.ico", response_class=FileResponse, include_in_schema=False)
def favicon():
    """浏览器默认请求；返回站内 SVG 图标（缺省时 204，避免日志刷 404）。"""
    path = STATIC_DIR / "favicon.svg"
    if path.is_file():
        return FileResponse(path, media_type="image/svg+xml")
    return PlainTextResponse(status_code=204)


# ── 体检记录 API ──


def _sanitize_filename(raw: str) -> str:
    """文件名清洗：只留文件名部分，替换 Windows/路径危险字符。"""
    name = Path(raw or "unnamed").name
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    return name.strip() or "unnamed"


def _row_dict(obj: Any) -> dict:
    """SQLAlchemy 行 → 纯字段 dict（剔除内部状态，可直接 JSON 序列化）。"""
    return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


@app.post("/api/exams", response_model=dict, status_code=201)
async def api_create_exams(
    files: list[UploadFile] = File(default=[]),
    exam_date: str = Form("", max_length=10),
    hospital: str = Form("", max_length=200),
    note: str = Form("", max_length=2000),
    session: AsyncSession = Depends(get_session),
):
    """批量上传体检图片：每张图 = 一条体检记录，本地 OCR 后存 ocr_text。

    单文件失败不影响其他文件；OCR 为 CPU 推理，在线程池执行。
    """
    if not files:
        raise HTTPException(
            status_code=400,
            detail={"code": 1002, "message": "未选择任何图片"},
        )
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=400,
            detail={"code": 1002, "message": f"单批最多上传 {MAX_UPLOAD_FILES} 张图片"},
        )
    date = exam_date.strip() or _today()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    results: list[dict[str, Any]] = []

    for upload in files:
        raw_name = upload.filename or "unnamed"
        filename = _sanitize_filename(raw_name)
        try:
            data = await upload.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError(f"文件超过大小上限 {settings.max_upload_size_mb}MB")
            if not data:
                raise ValueError("文件内容为空")
            ocr_text = await run_in_threadpool(ocr.ocr_image_bytes, data)
            if len(ocr_text) > settings.max_ocr_text_length:
                ocr_text = ocr_text[: settings.max_ocr_text_length]
            exam = await crud.create_exam(
                session,
                exam_date=date,
                hospital=hospital.strip(),
                source_type="image",
                note=note.strip(),
                source=raw_name,  # 来源/附件名称 = 原始文件名
                image_path="",  # 先入库拿 id，再落盘图片
                ocr_text=ocr_text,
            )
            # 原件落盘 data/uploads/{exam_id}/{filename}
            out_dir = Path(settings.uploads_dir) / str(exam.id)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / filename
            out_path.write_bytes(data)
            exam.image_path = f"uploads/{exam.id}/{filename}"
            await session.commit()
            await session.refresh(exam)
            results.append(
                {
                    "id": exam.id,
                    "exam_date": exam.exam_date,
                    "hospital": exam.hospital,
                    "source_type": exam.source_type,
                    "note": exam.note,
                    "source": exam.source,
                    "image_path": exam.image_path,
                    "ocr_text": exam.ocr_text,
                    "status": "created",
                    "message": "已入库",
                }
            )
        except Exception as e:
            logger.exception("上传图片处理失败: %s", raw_name)
            results.append(
                {
                    "id": None,
                    "exam_date": date,
                    "hospital": hospital,
                    "source_type": "image",
                    "note": note,
                    "source": raw_name,
                    "image_path": "",
                    "ocr_text": "",
                    "status": "failed",
                    "message": str(e) or "处理失败，请检查文件",
                }
            )
        finally:
            await upload.close()

    return {"code": 0, "data": {"results": results}, "message": "成功"}


@app.get("/api/exams", response_model=dict)
async def api_list_exams(session: AsyncSession = Depends(get_session)):
    """体检记录列表（新→旧），附带指标数。"""
    items = await crud.list_exams(session)
    return {"code": 0, "data": {"items": items}, "message": "成功"}


@app.get("/api/exams/{exam_id}", response_model=dict)
async def api_get_exam(exam_id: int, session: AsyncSession = Depends(get_session)):
    """体检记录详情：基本信息 + OCR 文本 + 指标列表。"""
    exam = await crud.get_exam(session, exam_id)
    if exam is None:
        raise HTTPException(
            status_code=404,
            detail={"code": 2004, "message": f"体检记录（id={exam_id}）不存在", "data": {"id": exam_id}},
        )
    metrics = await crud.list_metrics(session, exam_id)
    payload = ExamDetailOut(
        id=exam.id,
        exam_date=exam.exam_date,
        hospital=exam.hospital,
        source_type=exam.source_type,
        note=exam.note,
        source=exam.source,
        image_path=exam.image_path,
        ocr_text=exam.ocr_text,
        metric_count=len(metrics),
        created_at=exam.created_at,
        metrics=[_row_dict(m) for m in metrics],
    ).model_dump()
    return {"code": 0, "data": payload, "message": "成功"}


@app.get("/api/exams/{exam_id}/image")
async def api_exam_image(exam_id: int, session: AsyncSession = Depends(get_session)):
    """体检图片原件（浏览器 <img> 预览）。"""
    exam = await crud.get_exam(session, exam_id)
    if exam is None or not exam.image_path:
        raise HTTPException(
            status_code=404,
            detail={"code": 2004, "message": f"体检图片（id={exam_id}）不存在", "data": {"id": exam_id}},
        )
    path = Path(settings.data_dir) / exam.image_path
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail={"code": 2004, "message": f"体检图片文件缺失：{exam.image_path}", "data": {"id": exam_id}},
        )
    return FileResponse(str(path))


@app.put("/api/exams/{exam_id}", response_model=dict)
async def api_update_exam(
    exam_id: int, body: ExamUpdate, session: AsyncSession = Depends(get_session)
):
    """修改体检记录基本信息（日期/医院/备注/OCR 文本）。"""
    updated = await crud.update_exam(
        session,
        exam_id,
        exam_date=body.exam_date,
        hospital=body.hospital,
        source_type=body.source_type,
        note=body.note,
        source=body.source,
        ocr_text=body.ocr_text,
    )
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail={"code": 2004, "message": f"体检记录（id={exam_id}）不存在", "data": {"id": exam_id}},
        )
    return {"code": 0, "data": {"id": exam_id}, "message": "已保存"}


@app.delete("/api/exams/{exam_id}", response_model=dict)
async def api_delete_exam(exam_id: int, session: AsyncSession = Depends(get_session)):
    """删除体检记录：级联删指标 + 删除图片目录。"""
    exam = await crud.delete_exam(session, exam_id)
    if exam is None:
        raise HTTPException(
            status_code=404,
            detail={"code": 2004, "message": f"体检记录（id={exam_id}）不存在", "data": {"id": exam_id}},
        )
    # 清理图片目录（不阻断删除结果）
    if exam.image_path:
        out_dir = Path(settings.data_dir) / "uploads" / str(exam_id)
        shutil.rmtree(out_dir, ignore_errors=True)
    return {"code": 0, "data": {"id": exam_id}, "message": "已删除"}


# ── 指标 API ──


@app.get("/api/exams/{exam_id}/metrics", response_model=dict)
async def api_list_metrics(exam_id: int, session: AsyncSession = Depends(get_session)):
    """某次体检的指标列表。"""
    exam = await crud.get_exam(session, exam_id)
    if exam is None:
        raise HTTPException(
            status_code=404,
            detail={"code": 2004, "message": f"体检记录（id={exam_id}）不存在", "data": {"id": exam_id}},
        )
    metrics = await crud.list_metrics(session, exam_id)
    return {"code": 0, "data": {"items": [_row_dict(m) for m in metrics]}, "message": "成功"}


@app.post("/api/exams/{exam_id}/metrics", response_model=dict, status_code=201)
async def api_add_metric(
    exam_id: int, body: MetricIn, session: AsyncSession = Depends(get_session)
):
    """手工添加指标（AI 提取上线前的主要录入方式）。"""
    exam = await crud.get_exam(session, exam_id)
    if exam is None:
        raise HTTPException(
            status_code=404,
            detail={"code": 2004, "message": f"体检记录（id={exam_id}）不存在", "data": {"id": exam_id}},
        )
    metric = await crud.add_metric(session, exam_id, body)
    return {"code": 0, "data": _row_dict(metric), "message": "已添加"}


@app.put("/api/metrics/{metric_id}", response_model=dict)
async def api_update_metric(
    metric_id: int, body: MetricIn, session: AsyncSession = Depends(get_session)
):
    """修改指标。"""
    metric = await crud.update_metric(session, metric_id, body)
    if metric is None:
        raise HTTPException(
            status_code=404,
            detail={"code": 2004, "message": f"指标（id={metric_id}）不存在", "data": {"id": metric_id}},
        )
    return {"code": 0, "data": _row_dict(metric), "message": "已保存"}


@app.delete("/api/metrics/{metric_id}", response_model=dict)
async def api_delete_metric(metric_id: int, session: AsyncSession = Depends(get_session)):
    """删除指标。"""
    metric = await crud.delete_metric(session, metric_id)
    if metric is None:
        raise HTTPException(
            status_code=404,
            detail={"code": 2004, "message": f"指标（id={metric_id}）不存在", "data": {"id": metric_id}},
        )
    return {"code": 0, "data": {"id": metric_id}, "message": "已删除"}


# ── 日常身体数据 API ──


@app.get("/api/body-records", response_model=dict)
async def api_list_body_records(session: AsyncSession = Depends(get_session)):
    """日常身体数据列表（新→旧）。"""
    records = await crud.list_body_records(session)
    return {"code": 0, "data": {"items": [_row_dict(r) for r in records]}, "message": "成功"}


@app.post("/api/body-records", response_model=dict, status_code=201)
async def api_create_body_record(
    body: BodyRecordIn, session: AsyncSession = Depends(get_session)
):
    """新增一条日常身体数据（体重/血压/血糖等）。"""
    record = await crud.create_body_record(session, body)
    return {"code": 0, "data": _row_dict(record), "message": "已添加"}


@app.delete("/api/body-records/{record_id}", response_model=dict)
async def api_delete_body_record(
    record_id: int, session: AsyncSession = Depends(get_session)
):
    """删除一条日常身体数据。"""
    record = await crud.delete_body_record(session, record_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": 2004, "message": f"身体数据（id={record_id}）不存在", "data": {"id": record_id}},
        )
    return {"code": 0, "data": {"id": record_id}, "message": "已删除"}


# ── 模型管理 API（仅自定义模型）──

_CUSTOM_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,99}$")


def _custom_model_conflict(name: str, base_url: str, existing: dict[int, dict]) -> str | None:
    """新增自定义模型的冲突检查，返回冲突原因（None = 可添加）。"""
    if not _CUSTOM_MODEL_NAME_RE.match(name):
        return "模型名仅允许字母/数字与 . _ : / - （不能含空格或逗号）"
    for info in existing.values():
        if info["name"] == name and info.get("base_url") == base_url:
            return f"已存在同名同 API 地址的自定义模型「{name}」（不同厂商请换 API 地址录入）"
    return None


@app.get("/api/models", response_model=dict)
async def api_models(session: AsyncSession = Depends(get_session)):
    """可选 LLM 模型列表（仅自定义模型）+ 当前默认。"""
    custom_map = await crud.custom_models_map(session)
    llm.set_custom_models(custom_map)
    default = await llm.resolve_model(session, None)
    models = []
    for mid, info in custom_map.items():
        name = info["name"]
        host = (info.get("base_url") or "").split("://")[-1].split("/")[0]
        models.append(
            {
                "name": name,
                "value": f"{name}@{mid}",
                "display": f"{name} · {host}" if host else name,
                "custom": True,
                "id": mid,
            }
        )
    return {"code": 0, "data": {"models": models, "default": default}, "message": "成功"}


@app.get("/api/models/admin", response_model=dict)
async def api_models_admin(session: AsyncSession = Depends(get_session)):
    """模型管理列表：仅自定义模型行（custom=true）。"""
    custom_map = await crud.custom_models_map(session)
    llm.set_custom_models(custom_map)
    enabled_row = await crud.get_enabled_model(session)
    custom_items = [
        {
            "id": mid,
            "name": info["name"],
            "base_url": info["base_url"],
            "has_key": bool(info["api_key"]),
            "protocol": info.get("protocol", "openai"),
            "enabled": enabled_row is not None and enabled_row.id == mid,
            "env_default": False,
            "custom": True,
        }
        for mid, info in custom_map.items()
    ]
    enabled_route = (
        f"{enabled_row.name}@{enabled_row.id}"
        if enabled_row is not None and enabled_row.kind == "custom"
        else None
    )
    return {
        "code": 0,
        "data": {
            "items": custom_items,
            "enabled": enabled_route,
            "default": enabled_route,
        },
        "message": "成功",
    }


@app.post("/api/models/custom/detect", response_model=dict)
async def api_model_custom_detect(body: CustomModelCreate):
    """添加表单「测试协议」：探测该地址支持 OpenAI 兼容还是 Anthropic 协议（不落库）。"""
    results = await llm.detect_protocols(
        body.base_url, (body.api_key or "").strip(), (body.name or "").strip()
    )
    if not results:
        raise HTTPException(
            status_code=400,
            detail={
                "code": 1006,
                "message": "API 地址需为 http(s):// 开头的 OpenAI 兼容 / Anthropic 端点（不能含账号凭据或查询参数）",
            },
        )
    return {"code": 0, "data": {"results": results}, "message": "成功"}


@app.post("/api/models/custom", response_model=dict, status_code=201)
async def api_model_custom_add(
    body: CustomModelCreate, session: AsyncSession = Depends(get_session)
):
    """添加自定义模型：自带 OpenAI 兼容 / Anthropic 端点与 Key，任意厂商，不改 .env。"""
    name = (body.name or "").strip()
    protocol = (body.protocol or "").strip().lower()
    if protocol not in ("openai", "anthropic"):
        protocol = "openai"
    endpoint_url = llm._endpoint_for_protocol(body.base_url, protocol)
    if endpoint_url is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": 1006,
                "message": "API 地址需为 http(s):// 开头的 OpenAI 兼容 / Anthropic 端点（不能含账号凭据或查询参数）",
            },
        )
    existing = await crud.custom_models_map(session)
    conflict = _custom_model_conflict(name, endpoint_url, existing)
    if conflict:
        raise HTTPException(status_code=400, detail={"code": 1006, "message": conflict})
    api_key = (body.api_key or "").strip()
    new_id = await crud.add_custom_model(
        session, name, base_url=endpoint_url, api_key=api_key, protocol=protocol
    )
    llm.set_custom_models(
        {
            **existing,
            new_id: {
                "name": name,
                "base_url": endpoint_url,
                "api_key": api_key,
                "protocol": protocol,
            },
        }
    )
    return {
        "code": 0,
        "data": {
            "id": new_id,
            "name": name,
            "base_url": endpoint_url,
            "has_key": bool(api_key),
            "protocol": protocol,
            "custom": True,
        },
        "message": "成功",
    }


@app.delete("/api/models/custom/{model_id}", response_model=dict)
async def api_model_custom_delete(model_id: int, session: AsyncSession = Depends(get_session)):
    """删除自定义模型；历史 .env 遗留行不可删；删除启用中模型后 LLM 不可用。"""
    row = await session.get(models.ModelSetting, model_id)
    if row is None or row.kind != "custom":
        if row is not None and row.kind != "custom":
            raise HTTPException(
                status_code=400,
                detail={"code": 1002, "message": f"模型「{row.name}」是历史 .env 遗留行，不可在页面删除"},
            )
        raise HTTPException(
            status_code=404,
            detail={"code": 2004, "message": f"自定义模型（id={model_id}）不存在", "data": {"id": model_id}},
        )
    await crud.delete_custom_model(session, model_id)
    llm.set_custom_models(await crud.custom_models_map(session))
    return {"code": 0, "data": {"id": model_id, "name": row.name}, "message": "成功"}


@app.put("/api/models/custom/{model_id}", response_model=dict)
async def api_model_custom_update(
    model_id: int, body: CustomModelUpdate, session: AsyncSession = Depends(get_session)
):
    """修改自定义模型：改 API Key / base_url / protocol。Key 永不回显。"""
    row = await session.get(models.ModelSetting, model_id)
    if row is None or row.kind != "custom":
        raise HTTPException(
            status_code=404,
            detail={"code": 2004, "message": f"自定义模型（id={model_id}）不存在", "data": {"id": model_id}},
        )
    api_key = (body.api_key or "").strip() if body.api_key is not None else None
    base_url = (body.base_url or "").strip() if body.base_url is not None else None
    protocol = (body.protocol or "").strip().lower()
    if protocol and protocol not in ("openai", "anthropic"):
        raise HTTPException(
            status_code=400,
            detail={"code": 1006, "message": "protocol 仅支持 openai|anthropic"},
        )
    if base_url:
        endpoint_url = llm._endpoint_for_protocol(base_url, protocol or row.protocol)
        if endpoint_url is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": 1006,
                    "message": "API 地址需为 http(s):// 开头的 OpenAI 兼容 / Anthropic 端点（不能含账号凭据或查询参数）",
                },
            )
        base_url = endpoint_url
    updated = await crud.update_custom_model(
        session,
        model_id,
        api_key=api_key,
        base_url=base_url,
        protocol=protocol or None,
    )
    llm.set_custom_models(await crud.custom_models_map(session))
    assert updated is not None
    return {
        "code": 0,
        "data": {
            "id": model_id,
            "name": updated.name,
            "base_url": updated.base_url,
            "has_key": bool(updated.api_key),
            "protocol": updated.protocol,
            "custom": True,
        },
        "message": "成功",
    }


async def _validate_model_name(session: AsyncSession, name: str) -> str:
    """校验模型路由值：接受 {name}@{id}（同名精确行）或纯名（唯一自定义行）。"""
    name = (name or "").strip()
    custom_map = await crud.custom_models_map(session)
    llm.set_custom_models(custom_map)
    route_name, mid = llm._parse_route(name)
    if mid is not None:
        info = llm.custom_models().get(mid)
        if info is None or info.get("name") != route_name:
            raise HTTPException(
                status_code=400,
                detail={"code": 1002, "message": f"模型「{name}」不存在或已删除"},
            )
        return f"{route_name}@{mid}"
    custom_names = {info["name"] for info in custom_map.values()}
    if route_name in custom_names:
        matched = [i for i, info in custom_map.items() if info["name"] == route_name]
        if len(matched) == 1:
            return f"{route_name}@{matched[0]}"
        raise HTTPException(
            status_code=400,
            detail={"code": 1002, "message": f"模型「{route_name}」有多个自定义行，请使用 {route_name}@id 精确指定"},
        )
    raise HTTPException(
        status_code=400,
        detail={"code": 1002, "message": f"模型「{route_name}」不在自定义模型清单中，请先在模型设置中添加"},
    )


@app.post("/api/models/{name}/enable", response_model=dict)
async def api_model_enable(name: str, session: AsyncSession = Depends(get_session)):
    """启用自定义模型为问答默认（互斥：自动取消其他启用项）。"""
    name = await _validate_model_name(session, name)
    _route_name, mid = llm._parse_route(name)
    await crud.set_custom_model_enabled(session, mid, True)
    return {"code": 0, "data": {"enabled": name}, "message": "成功"}


@app.post("/api/models/{name}/disable", response_model=dict)
async def api_model_disable(name: str, session: AsyncSession = Depends(get_session)):
    """取消启用（无启用项时问答不可用，需在模型设置中添加并启用）。"""
    name = await _validate_model_name(session, name)
    _route_name, mid = llm._parse_route(name)
    await crud.set_custom_model_enabled(session, mid, False)
    return {"code": 0, "data": {"enabled": None}, "message": "成功"}


@app.post("/api/models/{name}/test", response_model=dict)
async def api_model_test(name: str, session: AsyncSession = Depends(get_session)):
    """连通探测：向该模型端点发最小请求，返回 ok/耗时/原因（诊断数据，恒 200）。"""
    name = await _validate_model_name(session, name)
    result = await llm.test_model(name)
    return {"code": 0, "data": {"model": name, **result}, "message": "成功"}


# ── 备份 API ──


def _backup_error(exc: Exception) -> HTTPException:
    """backup 模块异常 → HTTPException 统一映射。"""
    if isinstance(exc, backup_mod.BackupBusy):
        return HTTPException(status_code=409, detail={"code": 1008, "message": str(exc)})
    if isinstance(exc, FileNotFoundError):
        return HTTPException(
            status_code=404,
            detail={"code": 2005, "message": "备份文件不存在", "data": {"filename": str(exc)}},
        )
    if isinstance(exc, ValueError):  # 校验失败：路径穿越/非法条目/非本应用包/体积超限
        return HTTPException(status_code=400, detail={"code": 1007, "message": f"备份包校验失败：{exc}"})
    return HTTPException(
        status_code=500,
        detail={"code": 3004, "message": f"备份/还原执行失败（当前数据已回滚保护）：{exc}"},
    )


@app.get("/api/backup", response_model=dict)
async def api_backup_list():
    """备份清单（新→旧）：文件名/大小/时间/类型（manual|safety）/行数统计/损坏标记。"""
    items = await run_in_threadpool(backup_mod.list_backups)
    return {"code": 0, "data": {"items": items}, "message": "成功"}


@app.post("/api/backup", response_model=dict, status_code=201)
async def api_backup_create(body: BackupCreate):
    """一键备份当前全量数据（health.db + 上传原件）到 data/backups/。"""
    try:
        info = await run_in_threadpool(backup_mod.create_backup, body.label)
    except Exception as e:
        raise _backup_error(e)
    return {"code": 0, "data": info, "message": "备份完成"}


@app.get("/api/backup/{filename}")
async def api_backup_download(filename: str):
    """下载备份包（跨机迁移：下载后在目标机「从备份还原」上传）。"""
    path = backup_mod.backup_file(filename)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail={"code": 2005, "message": "备份文件不存在", "data": {"filename": filename}},
        )
    return FileResponse(str(path), media_type="application/gzip", filename=filename)


@app.post("/api/backup/upload", response_model=dict, status_code=201)
async def api_backup_upload(file: UploadFile = File(...)):
    """上传备份包入库（先解包校验：成员白名单/manifest/体积上限，非法包 1007 拒绝）。"""
    try:
        info = await run_in_threadpool(backup_mod.save_upload, file.file, file.filename or "")
    except Exception as e:
        raise _backup_error(e)
    finally:
        await file.close()
    return {"code": 0, "data": info, "message": "上传成功（校验通过）"}


@app.post("/api/backup/restore", response_model=dict)
async def api_backup_restore(body: BackupRestoreRequest):
    """从备份还原（自动先做 safety 快照；旧库改名留底 data/restore_<ts>.db 不自动删）。

    还原期间请求可能瞬时失败（引擎换绑窗口），属正常。
    """
    import app.db as db_module

    eng = db_module.engine
    if eng is not None:
        try:
            await eng.dispose()
        except Exception:
            logger.warning("还原前引擎池释放失败（继续尝试换位）", exc_info=True)
    try:
        result = await run_in_threadpool(backup_mod.restore_backup, body.filename)
    except Exception as e:
        raise _backup_error(e)
    return {"code": 0, "data": result, "message": "还原完成"}


@app.delete("/api/backup/{filename}", response_model=dict)
async def api_backup_delete(filename: str):
    """删除备份文件（仅 data/backups/ 内合法命名；穿越/不存在 → 404/1002）。"""
    if not backup_mod.safe_name(filename):
        raise HTTPException(status_code=400, detail={"code": 1002, "message": "备份文件名不合法"})
    try:
        deleted = await run_in_threadpool(backup_mod.delete_backup, filename)
    except Exception as e:
        raise _backup_error(e)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"code": 2005, "message": "备份文件不存在", "data": {"filename": filename}},
        )
    return {"code": 0, "data": {"filename": filename}, "message": "已删除"}


@app.post("/api/backup/restart", response_model=dict)
async def api_backup_restart(request: Request):
    """重启应用进程（还原/上传后无需手动上机）。"""
    import os

    root = Path(__file__).resolve().parent.parent
    script = root / "manage.sh"
    if not script.is_file() or not os.access(str(script), os.X_OK):
        raise HTTPException(
            status_code=500,
            detail={"code": 3005, "message": "未找到可执行的管理脚本 manage.sh"},
        )
    try:
        subprocess.Popen(
            ["bash", str(script), "restart"],
            cwd=str(root),
            env={**os.environ, "PYTHONUTF8": "1"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        logger.warning("restart 调用失败", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": 3005, "message": f"重启失败（请手动 ./manage.sh restart）：{e}"},
        )
    return {"code": 0, "data": {"ok": True}, "message": "已下发重启，请稍后刷新页面"}