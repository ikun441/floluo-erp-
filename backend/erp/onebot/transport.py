"""OneBot V11 reverse Universal WebSocket adapter, with no persistence access."""

import asyncio
import json
import logging
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from .. import message_gateway as gateway
from .events import InvalidOneBotEvent, normalize_message_event

logger = logging.getLogger("erp")
MAX_FRAME_BYTES = 65536


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("non_finite_json")


def register(app):
    @app.websocket("/onebot/v11/ws/{instance_id}")
    async def reverse_socket(ws: WebSocket, instance_id: str):
        auth = ws.headers.get("authorization", "")
        bot = ws.headers.get("x-self-id", "")
        if (
            ws.headers.get("origin") is not None
            or ws.query_params
            or ws.headers.get("x-client-role") != "Universal"
            or not auth.startswith("Bearer ")
            or not 32 <= len(auth[7:]) <= 128
            or len(bot) > 19
            or len(instance_id) > 36
            or not bot.isascii()
            or not bot.isdigit()
            or not 0 < int(bot) <= 2**63 - 1
        ):
            await ws.close(code=1008)
            return
        try:
            connection = await run_in_threadpool(
                gateway.authenticate, app.state.engine, instance_id, auth[7:], int(bot)
            )
        except gateway.ConnectionRejected:
            await ws.close(code=1008)
            return
        # The raw credential remains within this handshake's stack, never the application context.
        del auth
        await ws.accept()
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(ws.receive_text(), timeout=60)
                except TimeoutError:
                    await run_in_threadpool(gateway.check_alive, app.state.engine, connection)
                    continue
                if len(frame.encode("utf-8")) > MAX_FRAME_BYTES:
                    await ws.close(code=1009)
                    return
                payload = json.loads(
                    frame, object_pairs_hook=strict_object, parse_constant=reject_constant
                )
                await run_in_threadpool(gateway.check_alive, app.state.engine, connection)
                if not isinstance(payload, dict):
                    raise InvalidOneBotEvent("invalid_event")
                if payload.get("post_type") in {"meta_event", "notice", "request"}:
                    if (
                        type(payload.get("self_id")) is not int
                        or payload["self_id"] != connection.bot_id
                    ):
                        raise InvalidOneBotEvent("bot_identity_mismatch")
                    continue
                # API responses are not events and never enter a business parser.
                if "post_type" not in payload and "echo" in payload and "retcode" in payload:
                    continue
                event = normalize_message_event(
                    payload, instance_id=instance_id, expected_bot_id=connection.bot_id
                )
                reply = await run_in_threadpool(
                    gateway.process, app.state.engine, connection, event
                )
                if reply is not None:
                    await ws.send_json(
                        {
                            "action": "send_private_msg",
                            "params": {
                                "user_id": event.user_id,
                                "message": [
                                    {
                                        "type": "text",
                                        "data": {
                                            "text": json.dumps(
                                                reply, ensure_ascii=False, separators=(",", ":")
                                            )
                                        },
                                    }
                                ],
                            },
                            "echo": str(uuid4()),
                        }
                    )
        except WebSocketDisconnect:
            return
        except (ValueError, KeyError, RuntimeError):
            await run_in_threadpool(gateway.record_rejection, app.state.engine, connection)
            await ws.close(code=1008)
        except Exception:
            logger.error("onebot_request_failed")
            await ws.close(code=1011)
