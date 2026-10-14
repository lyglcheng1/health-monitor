# ===============================================================
# 文件: crud.py
# 项目: 健康数据监控（health-monitor）
# ===============================================================
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.schemas import BodyRecordIn, MetricIn


# ── 模型管理（仅自定义模型）──


async def get_enabled_model(session: AsyncSession) -> models.ModelSetting | None:
    """当前启用的模型行（互斥——全表至多一行 enabled=1）。"""
    return (
        await session.execute(
            select(models.ModelSetting)
            .where(models.ModelSetting.enabled == 1)
            .order_by(models.ModelSetting.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def set_custom_model_enabled(
    session: AsyncSession, model_id: int, enabled: bool
) -> bool:
    """启用/停用自定义模型（同样互斥）。返回是否找到该行。"""
    row = await session.get(models.ModelSetting, model_id)
    if row is None or row.kind != "custom":
        return False
    if enabled:
        await session.execute(update(models.ModelSetting).values(enabled=0))
    row.enabled = 1 if enabled else 0
    await session.commit()
    return True


async def list_custom_models(session: AsyncSession) -> list[models.ModelSetting]:
    return list(
        (
            await session.execute(
                select(models.ModelSetting)
                .where(models.ModelSetting.kind == "custom")
                .order_by(models.ModelSetting.id)
            )
        ).scalars()
    )


async def custom_models_map(session: AsyncSession) -> dict[int, dict]:
    """id → {name, base_url, api_key, protocol}（供 llm 路由注册表刷新）。"""
    rows = await list_custom_models(session)
    return {
        r.id: {
            "name": r.name,
            "base_url": r.base_url,
            "api_key": r.api_key,
            "protocol": r.protocol,
        }
        for r in rows
    }


async def add_custom_model(
    session: AsyncSession,
    name: str,
    *,
    base_url: str,
    api_key: str = "",
    protocol: str = "openai",
) -> int:
    row = models.ModelSetting(
        name=name, kind="custom", base_url=base_url, api_key=api_key, protocol=protocol
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row.id


async def delete_custom_model(session: AsyncSession, model_id: int) -> bool:
    row = await session.get(models.ModelSetting, model_id)
    if row is None or row.kind != "custom":
        return False
    await session.delete(row)
    await session.commit()
    return True


async def update_custom_model(
    session: AsyncSession,
    model_id: int,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    protocol: str | None = None,
) -> models.ModelSetting | None:
    row = await session.get(models.ModelSetting, model_id)
    if row is None or row.kind != "custom":
        return None
    if api_key is not None:
        row.api_key = api_key
    if base_url is not None:
        row.base_url = base_url
    if protocol:
        row.protocol = protocol
    await session.commit()
    await session.refresh(row)
    return row


# ── 体检记录 ──


async def create_exam(
    session: AsyncSession,
    *,
    exam_date: str,
    hospital: str = "",
    source_type: str = "image",
    note: str = "",
    source: str = "",
    image_path: str = "",
    ocr_text: str = "",
) -> models.Exam:
    row = models.Exam(
        exam_date=exam_date,
        hospital=hospital,
        source_type=source_type,
        note=note,
        source=source,
        image_path=image_path,
        ocr_text=ocr_text,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def get_exam(session: AsyncSession, exam_id: int) -> models.Exam | None:
    return await session.get(models.Exam, exam_id)


async def list_exams(
    session: AsyncSession, limit: int = 200
) -> list[dict]:
    """按日期倒序列出体检记录，附带指标数。"""
    rows = list(
        (
            await session.execute(
                select(models.Exam).order_by(
                    models.Exam.exam_date.desc(),
                    models.Exam.created_at.desc(),
                ).limit(limit)
            )
        ).scalars()
    )
    if not rows:
        return []
    counts = dict(
        (
            await session.execute(
                select(models.Metric.exam_id, func.count(models.Metric.id))
                .where(models.Metric.exam_id.in_([r.id for r in rows]))
                .group_by(models.Metric.exam_id)
            )
        ).all()
    )
    out = []
    for r in rows:
        d = {
            "id": r.id,
            "exam_date": r.exam_date,
            "hospital": r.hospital,
            "source_type": r.source_type,
            "note": r.note,
            "source": r.source,
            "image_path": r.image_path,
            "ocr_text": r.ocr_text,
            "metric_count": counts.get(r.id, 0),
            "created_at": r.created_at.isoformat(),
        }
        out.append(d)
    return out


async def update_exam(
    session: AsyncSession,
    exam_id: int,
    *,
    exam_date: str | None = None,
    hospital: str | None = None,
    source_type: str | None = None,
    note: str | None = None,
    source: str | None = None,
    ocr_text: str | None = None,
) -> models.Exam | None:
    row = await session.get(models.Exam, exam_id)
    if row is None:
        return None
    if exam_date is not None:
        row.exam_date = exam_date
    if hospital is not None:
        row.hospital = hospital
    if source_type is not None:
        row.source_type = source_type
    if note is not None:
        row.note = note
    if source is not None:
        row.source = source
    if ocr_text is not None:
        row.ocr_text = ocr_text
    await session.commit()
    await session.refresh(row)
    return row


async def delete_exam(session: AsyncSession, exam_id: int) -> models.Exam | None:
    row = await session.get(models.Exam, exam_id)
    if row is None:
        return None
    await session.delete(row)
    await session.commit()
    return row


# ── 指标 ──


async def list_metrics(session: AsyncSession, exam_id: int) -> list[models.Metric]:
    return list(
        (
            await session.execute(
                select(models.Metric)
                .where(models.Metric.exam_id == exam_id)
                .order_by(models.Metric.sort, models.Metric.id)
            )
        ).scalars()
    )


async def add_metric(
    session: AsyncSession, exam_id: int, data: MetricIn
) -> models.Metric:
    row = models.Metric(exam_id=exam_id, **data.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def update_metric(
    session: AsyncSession, metric_id: int, data: MetricIn
) -> models.Metric | None:
    row = await session.get(models.Metric, metric_id)
    if row is None:
        return None
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return row


async def delete_metric(session: AsyncSession, metric_id: int) -> models.Metric | None:
    row = await session.get(models.Metric, metric_id)
    if row is None:
        return None
    await session.delete(row)
    await session.commit()
    return row


# ── 3D 大屏聚合 ──


async def list_all_metrics_with_exam(session: AsyncSession):
    """全部指标 + 所属体检日期/医院/来源（按体检日期倒序），供 /api/body3d/overview 聚合。"""
    return list(
        (
            await session.execute(
                select(
                    models.Metric,
                    models.Exam.exam_date,
                    models.Exam.hospital,
                    models.Exam.source_type,
                )
                .join(models.Exam, models.Metric.exam_id == models.Exam.id)
                .order_by(models.Exam.exam_date.desc(), models.Metric.exam_id, models.Metric.sort)
            )
        ).all()
    )


# ── 日常身体数据 ──


async def create_body_record(
    session: AsyncSession, data: BodyRecordIn
) -> models.BodyRecord:
    row = models.BodyRecord(**data.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def list_body_records(
    session: AsyncSession, limit: int = 500
) -> list[models.BodyRecord]:
    return list(
        (
            await session.execute(
                select(models.BodyRecord)
                .order_by(
                    models.BodyRecord.record_date.desc(),
                    models.BodyRecord.created_at.desc(),
                )
                .limit(limit)
            )
        ).scalars()
    )


async def delete_body_record(
    session: AsyncSession, record_id: int
) -> models.BodyRecord | None:
    row = await session.get(models.BodyRecord, record_id)
    if row is None:
        return None
    await session.delete(row)
    await session.commit()
    return row