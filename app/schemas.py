# ===============================================================
# 文件: schemas.py
# 作者: chengge
# 最后修改: 2026-10-11
# ===============================================================

# ===============================================================
# 文件: schemas.py
# 项目: 健康数据监控（health-monitor）
# ===============================================================
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str
    password: str


# ── 体检记录 ──


class MetricIn(BaseModel):
    name: str = Field(..., max_length=100)
    value_text: str = Field("", max_length=100)
    unit: str = Field("", max_length=50)
    ref_low: str = Field("", max_length=50)
    ref_high: str = Field("", max_length=50)
    abnormal: bool = False
    body_part: str = Field("", max_length=50)
    note: str = Field("", max_length=500)
    sort: int = 0


class MetricOut(MetricIn):
    id: int
    exam_id: int
    model_config = ConfigDict(from_attributes=True)


class ExamOut(BaseModel):
    id: int
    exam_date: str
    hospital: str
    source: str = ""
    source_type: str
    note: str
    image_path: str
    ocr_text: str
    metric_count: int = 0
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ExamDetailOut(ExamOut):
    metrics: list[MetricOut] = []


class ExamUpdate(BaseModel):
    exam_date: str | None = Field(None, max_length=10)
    hospital: str | None = Field(None, max_length=200)
    source: str | None = Field(None, max_length=500)
    source_type: str | None = Field(None, max_length=20)
    note: str | None = None
    ocr_text: str | None = None


# ── 日常身体数据 ──


class BodyRecordIn(BaseModel):
    record_date: str = Field(..., max_length=10)
    record_type: str = Field(..., max_length=20)
    value: float
    unit: str = Field("", max_length=20)
    note: str = Field("", max_length=500)


class BodyRecordOut(BodyRecordIn):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ── 模型管理（仅自定义模型）──


class CustomModelCreate(BaseModel):
    name: str
    base_url: str
    api_key: str = ""
    protocol: str = "openai"


class CustomModelUpdate(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    protocol: str | None = None


# ── 备份 ──


class BackupCreate(BaseModel):
    label: str = ""


class BackupRestoreRequest(BaseModel):
    filename: str