from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(UTC)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Row:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Department(Row, Base):
    __tablename__ = "department"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), index=True)


class Position(Row, Base):
    __tablename__ = "position"
    name: Mapped[str] = mapped_column(String(120), unique=True)


class User(Row, Base):
    __tablename__ = "erp_user"
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), index=True)
    position_id: Mapped[str | None] = mapped_column(ForeignKey("position.id"), index=True)
    supervisor_id: Mapped[str | None] = mapped_column(ForeignKey("erp_user.id"), index=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(Row, Base):
    __tablename__ = "role"
    name: Mapped[str] = mapped_column(String(120), unique=True)


class UserRole(Base):
    __tablename__ = "user_role"
    user_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("role.id"), primary_key=True, index=True)


class PolicyRevision(Base):
    __tablename__ = "policy_revision"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    number: Mapped[int] = mapped_column(Integer, unique=True)
    author_id: Mapped[str | None] = mapped_column(ForeignKey("erp_user.id"), index=True)
    rules: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Gate(Base):
    __tablename__ = "authorization_gate"
    __table_args__ = (CheckConstraint("id = 1"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_id: Mapped[str | None] = mapped_column(ForeignKey("policy_revision.id"))


class SessionToken(Base):
    __tablename__ = "session_token"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf_digest: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Throttle(Base):
    __tablename__ = "auth_throttle"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Product(Row, Base):
    __tablename__ = "product"
    category_id: Mapped[str | None] = mapped_column(
        ForeignKey("category.id", name="fk_product_category_id_category"), index=True
    )
    sku: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    unit: Mapped[str] = mapped_column(String(30))
    owner_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditEvent(Base):
    __tablename__ = "audit_event"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("erp_user.id"), index=True)
    trace_id: Mapped[str] = mapped_column(String(36), index=True)
    event: Mapped[str] = mapped_column(String(160))
    result: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    previous_hash: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    format_version: Mapped[int] = mapped_column(Integer, default=2, server_default="1")
    details: Mapped[dict | None] = mapped_column(JSON)
