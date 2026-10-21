"""Transactional application boundary shared by protocol adapters."""

import hmac
import logging
from dataclasses import dataclass
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import message_service as service
from .audit import append, digest
from .database import lock_gate
from .message_models import MessageInbox, OneBotInstance
from .models import Throttle, now, uid

logger = logging.getLogger("erp")


class ConnectionRejected(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedConnection:
    instance_id: str
    bot_id: int
    token_digest: str


def verify_connection(db, connection):
    row = db.get(OneBotInstance, connection.instance_id)
    if (
        row is None
        or not row.active
        or row.bot_id != str(connection.bot_id)
        or not hmac.compare_digest(row.token_digest, connection.token_digest)
    ):
        raise ConnectionRejected("connection_denied")


def authenticate(engine, instance_id, token, bot_id):
    candidate = VerifiedConnection(instance_id, bot_id, digest(token))
    with Session(engine) as db:
        lock_gate(db)
        try:
            verify_connection(db, candidate)
        except ConnectionRejected:
            append(db, None, uid(), "onebot.connection", 403)
            db.commit()
            raise
        append(db, None, uid(), "onebot.connection", 200, {"instance_id": instance_id})
        db.commit()
    return candidate


def check_alive(engine, connection):
    with Session(engine) as db:
        verify_connection(db, connection)


def throttled(db, key, maximum):
    key = digest("onebot:" + key)
    row = db.get(Throttle, key)
    time = now()
    if row is None:
        row = Throttle(key=key, failures=0, window_start=time)
        db.add(row)
    if service.utc(row.window_start) + timedelta(minutes=1) <= time:
        row.failures, row.window_start = 0, time
    if row.failures >= maximum:
        return True
    row.failures += 1
    return False


def _process(engine, connection, event):
    if event.instance_id != connection.instance_id or event.bot_id != connection.bot_id:
        raise ConnectionRejected("event_identity_mismatch")
    with Session(engine, expire_on_commit=False) as db:
        lock_gate(db)
        verify_connection(db, connection)
        prior = db.get(MessageInbox, event.event_key)
        details = {"instance_id": event.instance_id, "event_key": event.event_key}
        if prior:
            collision = prior.payload_digest != event.payload_digest
            append(db, None, uid(), "onebot.replay", 409 if collision else 208, details)
            db.commit()
            if collision:
                raise ConnectionRejected("event_collision")
            return None
        # Fixed instance budget is checked before per-user keys to bound new throttle rows.
        limited = throttled(db, event.instance_id, 300)
        if not limited:
            limited = throttled(db, event.instance_id + ":" + str(event.user_id), 30)
        actor = service.bound_actor(db, event)
        reply, result, status = None, "rate_limited", 429
        if not limited:
            try:
                # Failed binding/application work rolls back independently of the durable inbox.
                with db.begin_nested():
                    actor, reply, result = service.dispatch(db, event)
                status = 403 if result in {"group_blocked", "unbound"} else 200
            except HTTPException as exc:
                status, result = exc.status_code, "denied"
                if event.chat_type == "private":
                    reply = {
                        "status": "denied",
                        "message": "操作被拒绝，请检查Web权限或重新签发绑定码。",
                    }
        db.add(
            MessageInbox(
                event_key=event.event_key,
                instance_id=event.instance_id,
                payload_digest=event.payload_digest,
                result=result,
            )
        )
        append(db, actor, uid(), "onebot.message", status, details)
        db.commit()
        # Replies are returned only after the authorization/inbox transaction commits.
        return reply


def record_rejection(engine, connection, status=400):
    with Session(engine) as db:
        lock_gate(db)
        append(db, None, uid(), "onebot.rejected", status, {"instance_id": connection.instance_id})
        db.commit()


def process(engine, connection, event):
    try:
        return _process(engine, connection, event)
    except ConnectionRejected:
        raise
    except Exception:
        # The processing Session has already rolled back. A failure never returns a reply.
        try:
            record_rejection(engine, connection, 500)
        except Exception:
            logger.error("onebot_failure_audit_unavailable")
        logger.error("onebot_message_failed")
        raise
