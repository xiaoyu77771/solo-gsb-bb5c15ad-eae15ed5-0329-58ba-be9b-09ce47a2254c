"""ORM 模型。"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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
