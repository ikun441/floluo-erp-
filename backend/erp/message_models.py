"""Persistent message identity; raw messages and bearer credentials are never stored."""

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

from .models import Base, Row, now


class OneBotInstance(Row, Base):
    __tablename__ = "onebot_instance"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    bot_id: Mapped[str] = mapped_column(String(20))
    token_digest: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MessageBinding(Row, Base):
    __tablename__ = "message_binding"
    __table_args__ = (
        UniqueConstraint("instance_id", "platform_user_id"),
        UniqueConstraint("instance_id", "owner_id"),
    )
    instance_id: Mapped[str] = mapped_column(ForeignKey("onebot_instance.id"), index=True)
    platform_user_id: Mapped[str] = mapped_column(String(20))
    owner_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class BindingChallenge(Base):
    __tablename__ = "binding_challenge"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    instance_id: Mapped[str] = mapped_column(ForeignKey("onebot_instance.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    platform_user_id: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MessageInbox(Base):
    __tablename__ = "message_inbox"
    event_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    instance_id: Mapped[str] = mapped_column(ForeignKey("onebot_instance.id"), index=True)
    payload_digest: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(40))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class MessageOperation(Row, Base):
    __tablename__ = "message_operation"
    __table_args__ = (
        CheckConstraint(
            "state IN ('collecting_missing','awaiting_confirmation','completed','cancelled','expired')"
        ),
        CheckConstraint("resource = 'purchase_orders'"),
        CheckConstraint(
            "(binding_id IS NULL AND binding_version IS NULL) OR (binding_id IS NOT NULL AND binding_version IS NOT NULL AND binding_version >= 1)"
        ),
        CheckConstraint(
            "(state = 'completed' AND result_id IS NOT NULL AND confirmed_version IS NOT NULL) OR (state <> 'completed' AND result_id IS NULL AND confirmed_version IS NULL)"
        ),
        CheckConstraint(
            "state NOT IN ('awaiting_confirmation','completed') OR preview_digest IS NOT NULL"
        ),
        CheckConstraint("result_id IS NULL OR result_id = target_order_id"),
    )
    owner_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    binding_id: Mapped[str | None] = mapped_column(ForeignKey("message_binding.id"), index=True)
    binding_version: Mapped[int | None] = mapped_column(Integer)
    resource: Mapped[str] = mapped_column(String(40), default="purchase_orders")
    payload: Mapped[dict] = mapped_column(JSON)
    target_order_id: Mapped[str] = mapped_column(String(36), unique=True)
    state: Mapped[str] = mapped_column(String(30), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    preview_digest: Mapped[str | None] = mapped_column(String(64))
    result_id: Mapped[str | None] = mapped_column(ForeignKey("purchase_order.id"), unique=True)
    confirmed_version: Mapped[int | None] = mapped_column(Integer)


class OneBotConnection(Row, Base):
    __tablename__ = "onebot_connection"
    __table_args__ = (
        CheckConstraint("state IN ('connected','disconnected')"),
        CheckConstraint("instance_version >= 1"),
    )
    instance_id: Mapped[str] = mapped_column(ForeignKey("onebot_instance.id"), unique=True)
    connection_id: Mapped[str] = mapped_column(String(36), unique=True)
    instance_version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnect_reason: Mapped[str | None] = mapped_column(String(32))


class MessageDelivery(Row, Base):
    __tablename__ = "message_delivery"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','awaiting_ack','delivered','failed','suppressed','expired')"
        ),
        CheckConstraint("attempts BETWEEN 0 AND 3"),
        CheckConstraint(
            "(binding_id IS NULL AND binding_version IS NULL) OR (binding_id IS NOT NULL AND binding_version IS NOT NULL AND binding_version >= 1)"
        ),
        CheckConstraint(
            "state <> 'awaiting_ack' OR (attempt_token IS NOT NULL AND attempt_connection_id IS NOT NULL AND attempts >= 1)"
        ),
        CheckConstraint(
            "(state = 'delivered' AND delivered_at IS NOT NULL) OR (state <> 'delivered' AND delivered_at IS NULL)"
        ),
        Index("ix_message_delivery_due", "instance_id", "state", "next_attempt_at"),
    )
    event_key: Mapped[str] = mapped_column(ForeignKey("message_inbox.event_key"), unique=True)
    instance_id: Mapped[str] = mapped_column(ForeignKey("onebot_instance.id"), index=True)
    recipient_id: Mapped[str] = mapped_column(String(20))
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("erp_user.id"), index=True)
    binding_id: Mapped[str | None] = mapped_column(ForeignKey("message_binding.id"), index=True)
    binding_version: Mapped[int | None] = mapped_column(Integer)
    recipe: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempt_token: Mapped[str | None] = mapped_column(String(36))
    attempt_connection_id: Mapped[str | None] = mapped_column(String(36))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(32))
