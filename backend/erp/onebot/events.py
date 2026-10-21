"""Fail-closed normalization of OneBot V11 message events."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

MAX_EVENT_TEXT = 4096
MAX_SEGMENTS = 100


class InvalidOneBotEvent(ValueError):
    """The event cannot safely enter the command pipeline."""


def _integer(value: Any, *, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    instance_id: str
    bot_id: int
    user_id: int
    chat_type: str
    chat_id: int
    message_id: int
    text: str
    event_key: str
    payload_digest: str


def normalize_message_event(
    payload: Any, *, instance_id: str, expected_bot_id: int
) -> IncomingMessage:
    """Validate a private/group message event; sender metadata is never identity authority."""
    if not isinstance(instance_id, str) or not instance_id or len(instance_id) > 128:
        raise InvalidOneBotEvent("invalid_instance")
    if not isinstance(payload, dict) or payload.get("post_type") != "message":
        raise InvalidOneBotEvent("unsupported_event")
    if payload.get("message_type") not in {"private", "group"}:
        raise InvalidOneBotEvent("unsupported_message_type")
    if payload.get("sub_type") == "anonymous":
        raise InvalidOneBotEvent("anonymous_group_message")
    if not _integer(expected_bot_id, minimum=1, maximum=2**63 - 1):
        raise InvalidOneBotEvent("invalid_expected_bot")
    for field, low, high in (
        ("self_id", 1, 2**63 - 1),
        ("user_id", 1, 2**63 - 1),
        ("time", 0, 2**63 - 1),
        ("message_id", -(2**31), 2**31 - 1),
    ):
        if not _integer(payload.get(field), minimum=low, maximum=high):
            raise InvalidOneBotEvent("invalid_" + field)
    bot_id = payload["self_id"]
    if bot_id != expected_bot_id:
        raise InvalidOneBotEvent("bot_identity_mismatch")
    kind = payload["message_type"]
    if kind == "group":
        if not _integer(payload.get("group_id"), minimum=1, maximum=2**63 - 1):
            raise InvalidOneBotEvent("invalid_group_id")
        chat_id = payload["group_id"]
    else:
        chat_id = payload["user_id"]
    segments = payload.get("message")
    if not isinstance(segments, list) or not segments or len(segments) > MAX_SEGMENTS:
        raise InvalidOneBotEvent("invalid_message_segments")
    parts: list[str] = []
    for segment in segments:
        if not isinstance(segment, dict) or segment.get("type") != "text":
            raise InvalidOneBotEvent("non_text_segment")
        data = segment.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("text"), str):
            raise InvalidOneBotEvent("invalid_text_segment")
        parts.append(data["text"])
    text = "".join(parts)
    if not text.strip() or len(text) > MAX_EVENT_TEXT:
        raise InvalidOneBotEvent("invalid_text_length")
    try:
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (TypeError, ValueError) as exc:
        raise InvalidOneBotEvent("invalid_event_payload") from exc
    event_identity = "\0".join(
        (
            instance_id,
            str(bot_id),
            kind,
            str(chat_id),
            str(payload["user_id"]),
            str(payload["message_id"]),
        )
    )
    event_key = hashlib.sha256(event_identity.encode()).hexdigest()
    return IncomingMessage(
        instance_id,
        bot_id,
        payload["user_id"],
        kind,
        chat_id,
        payload["message_id"],
        text,
        event_key,
        hashlib.sha256(canonical).hexdigest(),
    )
