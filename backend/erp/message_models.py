"""Persistent message identity; raw messages and bearer credentials are never stored."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
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
