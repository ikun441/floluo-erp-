import json
from pathlib import Path

import pytest
from erp.onebot.events import InvalidOneBotEvent, normalize_message_event
from erp.onebot.intent import parse_fixed_command

FIXTURES = Path(__file__).parent / "fixtures" / "onebot_command_cases.json"


def test_fixed_command_fixtures():
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    assert len(cases) == 8
    assert all(
        ((result := parse_fixed_command(case["text"])).intent is not None) == case["valid"]
        for case in cases
    )
    for case in cases:
        result = parse_fixed_command(case["text"])
        assert list(result.missing) == case["missing"]


def event(**updates):
    value = {
        "time": 1,
        "self_id": 10001,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": -7,
        "user_id": 20002,
        "message": [{"type": "text", "data": {"text": "/erp 库存 查询 mouse"}}],
        "sender": {"user_id": 99999, "role": "owner"},
    }
    value.update(updates)
    return value


def test_event_normalization_stable_dedupes_with_context_and_ignores_sender_role():
    first = normalize_message_event(event(), instance_id="onebot-a", expected_bot_id=10001)
    second = normalize_message_event(
        event(sender={"user_id": 1, "role": "admin"}), instance_id="onebot-a", expected_bot_id=10001
    )
    other_instance = normalize_message_event(event(), instance_id="onebot-b", expected_bot_id=10001)
    assert first.user_id == 20002
    assert first.event_key == second.event_key
    assert first.event_key != other_instance.event_key
    assert first.payload_digest != second.payload_digest


@pytest.mark.parametrize(
    "payload",
    [
        event(self_id=999),
        event(message_type="discuss"),
        event(message_type="group", sub_type="anonymous", group_id=300),
        event(
            message=[
                {"type": "text", "data": {"text": "/erp 库存 查询 x"}},
                {"type": "image", "data": {"file": "x"}},
            ]
        ),
        event(message="[CQ:at,qq=all] /erp 库存 查询 x"),
        event(user_id=True),
        event(message_id=2**40),
    ],
)
def test_rejects_untrusted_or_unsupported_event_shapes(payload):
    with pytest.raises(InvalidOneBotEvent):
        normalize_message_event(payload, instance_id="onebot-a", expected_bot_id=10001)


def test_group_context_is_separate_from_private_context():
    private = normalize_message_event(event(), instance_id="onebot-a", expected_bot_id=10001)
    group = normalize_message_event(
        event(message_type="group", sub_type="normal", group_id=300),
        instance_id="onebot-a",
        expected_bot_id=10001,
    )
    assert group.chat_id == 300
    assert group.chat_type == "group"
    assert group.event_key != private.event_key


def test_command_boundaries_and_malformed_values_fail_closed():
    for command in (
        "/erp 采购 新增 商品=mouse 数量=NaN 单价=1 供应商=s 币种=CNY",
        "/erp 采购 新增 商品=mouse 数量=1.00001 单价=1 供应商=s 币种=CNY",
        "/erp 采购 新增 商品=mouse 数量=1 单价=1.001 供应商=s 币种=CNY",
        "/erp 采购 新增 商品=mouse 数量=1 数量=1 单价=1 供应商=s 币种=CNY",
        "/erp 采购 新增 商品=mouse 数量=1 单价=1 供应商=s 币种=CNY 角色=admin",
    ):
        assert parse_fixed_command(command).intent is None
    assert parse_fixed_command("/erp" + " x" * 5000).error == "invalid_message"
