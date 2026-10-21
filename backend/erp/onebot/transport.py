"""OneBot V11 reverse Universal WebSocket adapter, with no persistence access."""

import asyncio
import json
import logging

import anyio
from fastapi import WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from .. import delivery_service as deliveries
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
            connection = await run_in_threadpool(
                gateway.open_connection, app.state.engine, connection
            )
        except gateway.ConnectionRejected:
            await ws.close(code=1008)
            return
        # The raw credential remains within this handshake's stack, never the application context.
        del auth
        receive_task = None
        reason = "peer_closed"
        try:
            await ws.accept()
            while True:
                await run_in_threadpool(gateway.check_alive, app.state.engine, connection)
                # A single leased writer owns all sends; no untracked background task.
                for _ in range(5):
                    action = await run_in_threadpool(deliveries.claim, app.state.engine, connection)
                    if action is None:
                        break
                    await asyncio.wait_for(ws.send_json(action), timeout=5)
                if receive_task is None:
                    receive_task = asyncio.create_task(ws.receive_text())
                try:
                    frame = await asyncio.wait_for(asyncio.shield(receive_task), timeout=2)
                except TimeoutError:
                    continue
                receive_task = None
                if len(frame.encode("utf-8")) > MAX_FRAME_BYTES:
                    reason = "protocol_error"
                    await ws.close(code=1009)
                    return
                payload = json.loads(
                    frame, object_pairs_hook=strict_object, parse_constant=reject_constant
                )
                await run_in_threadpool(gateway.check_alive, app.state.engine, connection, True)
                if not isinstance(payload, dict):
                    raise InvalidOneBotEvent("invalid_event")
                if payload.get("post_type") in {"meta_event", "notice", "request"}:
                    if (
                        type(payload.get("self_id")) is not int
                        or payload["self_id"] != connection.bot_id
                    ):
                        raise InvalidOneBotEvent("bot_identity_mismatch")
                    continue
                if "post_type" not in payload and "echo" in payload and "retcode" in payload:
                    await run_in_threadpool(
                        deliveries.acknowledge, app.state.engine, connection, payload
                    )
                    continue
                event = normalize_message_event(
                    payload, instance_id=instance_id, expected_bot_id=connection.bot_id
                )
                await run_in_threadpool(gateway.process, app.state.engine, connection, event)
        except WebSocketDisconnect:
            return
        except gateway.ConnectionRejected:
            reason = "auth_changed"
            await run_in_threadpool(gateway.record_rejection, app.state.engine, connection, 403)
            await ws.close(code=1008)
        except (ValueError, KeyError, RuntimeError):
            reason = "protocol_error"
            await run_in_threadpool(gateway.record_rejection, app.state.engine, connection)
            await ws.close(code=1008)
        except Exception:
            reason = "transport_error"
            logger.error("onebot_request_failed")
            await ws.close(code=1011)
        finally:
            # TestClient/server shutdown may cancel this scope before a receive task settles.
            # Release the fenced lease first, under cancellation shielding.
            with anyio.CancelScope(shield=True):
                if receive_task is not None:
                    receive_task.cancel()
                try:
                    await run_in_threadpool(
                        gateway.close_connection, app.state.engine, connection, reason
                    )
                except Exception:
                    logger.error("onebot_disconnect_record_failed")
                finally:
                    if receive_task is not None:
                        await asyncio.gather(receive_task, return_exceptions=True)
