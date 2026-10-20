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
    parts = [
        event.actor_id,
        event.trace_id,
        event.event,
        event.result,
        timestamp,
        event.previous_hash,
    ]
    if event.format_version == 2:
        parts.extend([2, event.details])
    elif event.format_version != 1:
        raise ValueError("unsupported audit format")
    return json.dumps(
        parts,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def append(db, actor, trace, event, status, details=None):
    previous = db.scalar(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1))
    row = AuditEvent(
        format_version=2,
        details=details,
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
        if (
            row.format_version not in {1, 2}
            or row.previous_hash != previous
            or row.digest != digest(payload(row))
        ):
            return False
        previous = row.digest
    return True


def change_summary(resource, record_id, before, after, changed):
    def summary(data):
        if data is None:
            return None
        safe = {
            key: value
            for key, value in data.items()
            if key not in {"password", "password_hash", "contact", "phone", "role_ids"}
        }
        return {
            "version": data.get("version"),
            "fingerprint": digest(
                json.dumps(safe, ensure_ascii=False, sort_keys=True, default=str)
            ),
        }

    return {
        "resource": resource,
        "record_id": record_id,
        "changed_fields": sorted(changed),
        "before": summary(before),
        "after": summary(after),
    }
