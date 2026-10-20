import hashlib
import json
from datetime import UTC

from sqlalchemy import select

from .models import AuditEvent, now


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def payload(event):
    value = event.created_at
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    timestamp = value.replace(tzinfo=None).isoformat(timespec="microseconds")
    return json.dumps(
        [event.actor_id, event.trace_id, event.event, event.result, timestamp, event.previous_hash],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def append(db, actor, trace, event, status):
    previous = db.scalar(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1))
    row = AuditEvent(
        actor_id=actor,
        trace_id=trace,
        event=event,
        result=status,
        created_at=now(),
        previous_hash=previous.digest if previous else "0" * 64,
    )
    row.digest = digest(payload(row))
    db.add(row)
    db.flush()


def verify(db):
    previous = "0" * 64
    for row in db.scalars(select(AuditEvent).order_by(AuditEvent.seq)):
        if row.previous_hash != previous or row.digest != digest(payload(row)):
            return False
        previous = row.digest
    return True
