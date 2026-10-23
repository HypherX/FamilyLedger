from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    note: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="member")


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(180))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(16), default="csv")
    account_name: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="running")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    added: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    duplicate: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text, default="")
    period_start: Mapped[str] = mapped_column(String(10), default="")
    period_end: Mapped[str] = mapped_column(String(10), default="")
    stored_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_transaction_fingerprint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    direction: Mapped[str] = mapped_column(String(16))
    amount_cents: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(16), default="其他支出")
    title: Mapped[str] = mapped_column(String(40), default="")
    counterparty: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    pay_method: Mapped[str] = mapped_column(String(40), default="")
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    included: Mapped[bool] = mapped_column(Boolean, default=True)

    batch: Mapped[ImportBatch] = relationship(back_populates="transactions")
    member: Mapped[Member | None] = relationship(back_populates="transactions")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_on: Mapped[str] = mapped_column(String(10), default="")
    end_on: Mapped[str] = mapped_column(String(10), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
