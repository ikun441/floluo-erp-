from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, Row


class AIConfiguration(Base):
    __tablename__ = "ai_configuration"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_ai_configuration_singleton"),
        CheckConstraint("timeout_seconds BETWEEN 2 AND 20", name="ck_ai_timeout"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    base_url: Mapped[str] = mapped_column(String(500), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10)
    tools: Mapped[list] = mapped_column(JSON, default=list)


class AIRequest(Row, Base):
    __tablename__ = "ai_request"
    __table_args__ = (
        CheckConstraint(
            "state IN ('parsing','ready','clarification','failed','cancelled')",
            name="ck_ai_request_state",
        ),
        CheckConstraint(
            "(state IN ('ready','clarification') AND intent IS NOT NULL) OR "
            "(state IN ('parsing','failed','cancelled') AND intent IS NULL)",
            name="ck_ai_request_intent",
        ),
        UniqueConstraint("owner_id", "request_key", name="uq_ai_request_owner_key"),
        Index("ix_ai_request_owner_created", "owner_id", "created_at"),
        Index("ix_ai_request_state_lease", "state", "lease_expires_at"),
    )
    owner_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"))
    session_digest: Mapped[str] = mapped_column(ForeignKey("session_token.digest"))
    request_key: Mapped[str] = mapped_column(String(128))
    payload_digest: Mapped[str] = mapped_column(String(64))
    config_version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))
    intent: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(String(60))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIHandoff(Base):
    """One explicit human transfer per source request; business confirmation stays separate."""

    __tablename__ = "ai_handoff"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_ai_handoff_operation"),
        CheckConstraint("source_version >= 1", name="ck_ai_handoff_version"),
    )
    request_id: Mapped[str] = mapped_column(ForeignKey("ai_request.id"), primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("message_operation.id"))
    source_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
