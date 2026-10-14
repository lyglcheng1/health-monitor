# ===============================================================
# 文件: models.py
# 项目: 健康数据监控（health-monitor）
# ===============================================================
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.utcnow()


class Base(DeclarativeBase):
    pass


class Exam(Base):
    """一次体检/检查记录：一张图片（扫描件）即一条记录。

    source: 来源/附件名称——说明这份数据来自哪个文件，如
        「连云港第一人民医院20260930检查.pdf 第6/6页（检验报告单）」。
    source_type: image（照片/扫描件）| pdf（后续扩展）；目前默认 image。
    ocr_text: RapidOCR 识别出的原文（AI 提取的输入）。
    extracted_json: 预留——LLM 结构化提取结果（指标列表）落这里，后续迭代实现。
    """

    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    hospital: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="image")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    ocr_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extracted_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    metrics: Mapped[list["Metric"]] = relationship(
        back_populates="exam",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Metric(Base):
    """体检指标：归属某次体检，名称 + 数值文本 + 单位 + 参考范围 + 异常标记。

    value_text 用字符串保存，兼容化验单上的范围写法（如 "<0.1"、"1.2-3.4"）；
    abnormal 供 3D 人体标注问题部位使用（后续大屏按 body_part 聚合）。
    """

    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    value_text: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    ref_low: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    ref_high: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    abnormal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    body_part: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    exam: Mapped["Exam"] = relationship(back_populates="metrics")


class BodyRecord(Base):
    """日常身体数据：体重/血压/血糖等，独立于体检记录（可每天录入）。

    record_type: weight | blood_pressure | blood_glucose | ...（前端自由填）
    value: 数值（血压可存收缩压，舒张压放 note 或另建一行）
    """

    __tablename__ = "body_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class ModelSetting(Base):
    """LLM 模型管理：页面维护的自定义模型（OpenAI 兼容 / Anthropic 端点）。

    kind='custom'：页面自助添加的端点（任意厂商），api_key 仅存本地；
    kind='env'：历史遗留（旧版 .env 清单行，不再使用）。
    路由值 {name}@{id} 区分同名多行。无启用行时 LLM 不可用。
    """

    __tablename__ = "model_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="env")
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    api_key: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    protocol: Mapped[str] = mapped_column(String(10), nullable=False, default="openai")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )