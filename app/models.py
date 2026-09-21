"""ORM 模型。"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


def _utcnow():
    return datetime.now(timezone.utc)


from .database import Base  # noqa: E402


class Reagent(Base):
    __tablename__ = "reagents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    cas: Mapped[str | None] = mapped_column(String(64))
    formula: Mapped[str | None] = mapped_column(String(128))
    concentration: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="liquid")  # liquid/solid/gas
    categories: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组：类别标签
    note: Mapped[str | None] = mapped_column(Text)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    steps: Mapped[list["Step"]] = relationship(back_populates="reagent")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    steps: Mapped[list["Step"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="Step.order_index"
    )


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    time_offset_min: Mapped[float | None] = mapped_column(Float)  # 相对起始的加液时刻（分钟）
    reagent_id: Mapped[int | None] = mapped_column(
        ForeignKey("reagents.id", ondelete="RESTRICT"), nullable=True
    )
    # 临时（未建档）试剂名快照与类别，便于即便试剂被删仍可展示/推演
    reagent_name: Mapped[str] = mapped_column(String(128), default="")
    categories: Mapped[str] = mapped_column(Text, default="[]")  # 临时试剂的类别 JSON
    amount_ml: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)

    plan: Mapped["Plan"] = relationship(back_populates="steps")
    reagent: Mapped["Reagent | None"] = relationship(back_populates="steps")


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # R001 / C001 ...
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(64), nullable=False)
    directional: Mapped[bool] = mapped_column(Boolean, default=False)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    title: Mapped[str] = mapped_column(String(256), default="")
    reaction: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    references: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("plans.id", ondelete="SET NULL"), nullable=True
    )
    plan_name: Mapped[str] = mapped_column(String(128), default="")
    rule_revision: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="safe")  # safe/warning/danger
    report: Mapped[str] = mapped_column(Text)  # 完整推演报告 JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RuleScheme(Base):
    """规则方案：一组相容性规则的命名集合，其下按版本管理规则快照。"""

    __tablename__ = "rule_schemes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    versions: Mapped[list["RuleSchemeVersion"]] = relationship(
        back_populates="scheme",
        cascade="all, delete-orphan",
        order_by="RuleSchemeVersion.version_no",
    )


class RuleSchemeVersion(Base):
    """规则方案版本：发布时冻结的规则快照（含严重级别依据）与生命周期时间戳。

    status 流转：draft（草稿，可编辑）→ published（已发布/当前生效）→ disabled（已停用）。
    同一方案同一时刻至多一个 published 版本；发布新版本会自动停用旧版本。
    """

    __tablename__ = "rule_scheme_versions"
    __table_args__ = (
        UniqueConstraint("scheme_id", "version_no", name="uq_scheme_version_no"),
    )

    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_DISABLED = "disabled"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme_id: Mapped[int] = mapped_column(
        ForeignKey("rule_schemes.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_DRAFT)
    note: Mapped[str | None] = mapped_column(Text)  # 变更说明
    rules: Mapped[str] = mapped_column(Text, default="[]")  # 规则快照 JSON 数组
    source_revision: Mapped[str] = mapped_column(String(64), default="")  # 快照来源规则图版本
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime)

    scheme: Mapped["RuleScheme"] = relationship(back_populates="versions")
