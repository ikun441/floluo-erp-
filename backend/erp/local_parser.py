"""Bounded, offline rules. No database, network, identity or execution capabilities."""

import re
import shlex
from dataclasses import replace

from .intent import MAX_MESSAGE_LENGTH, BusinessIntent, ParseResult, parse_fixed_command

UNITS = "千克|公斤|个|件|台|箱|套|只|支|米|包|批"
NUMBER = r"[0-9]+(?:\.[0-9]+)?"
PREFIX = r"(?:请)?(?:帮我)?"
INVENTORY = (
    re.compile(PREFIX + r"(?:查询一下|查一下|查询)\s*(.+?)\s*(?:还有多少库存|的库存|库存)"),
    re.compile(PREFIX + r"(.+?)\s*还有多少库存"),
)
PURCHASE_QUERY = re.compile(
    PREFIX + r"(?:查询一下|查一下|查询)采购订单(?:\s+([A-Za-z0-9-]{1,160}))?"
)
PURCHASE = re.compile(PREFIX + r"(?:登记)?采购\s*(" + NUMBER + r")\s*(" + UNITS + r")\s*(.+)")
PRICE = re.compile(r"(?:单价|每(" + UNITS + r"))\s*(" + NUMBER + r")\s*元")


def _entity(value: str) -> str | None:
    value = value.strip()
    if not value or len(value) > 160:
        return None
    # Quotes mark a literal name, including otherwise ambiguous conjunctions.
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("“") and value.endswith("”")
    ):
        inner = value[1:-1]
        if inner.strip() and not any(c in inner for c in '\r\n"“”'):
            return inner
        return None
    if re.search(r'[和及与并或,，;；。！？!?/\\=：:"“”+]', value) or any(
        word in value for word in ("然后", "忽略", "执行", "删除", "提交", "审批", "入库")
    ):
        return None
    return value


def _clauses(text: str) -> list[str] | None:
    result, start, closing = [], 0, None
    for index, char in enumerate(text):
        if closing:
            if char == closing:
                closing = None
        elif char in {'"', "“"}:
            closing = '"' if char == '"' else "”"
        elif char == "”":
            return None
        elif char in {",", "，"}:
            result.append(text[start:index].strip())
            start = index + 1
    if closing:
        return None
    result.append(text[start:].strip())
    return result if all(result) else None


def parse_local_text(text: str) -> ParseResult:
    """Recognize one complete supported sentence; uncertainty produces no intent."""
    if not isinstance(text, str) or not text or len(text) > MAX_MESSAGE_LENGTH:
        return ParseResult(None, error="invalid_message")
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        return ParseResult(None, error="unsupported_local_text")
    text = text.strip()
    if text[-1:] in {"。", "？", "?", "！", "!"}:
        text = text[:-1].strip()
    for pattern in INVENTORY:
        match = pattern.fullmatch(text)
        entity = _entity(match[1]) if match else None
        if entity:
            return ParseResult(
                BusinessIntent("query", "inventory", {"query": entity}, {}, 0.95, "local_rule")
            )
    if match := PURCHASE_QUERY.fullmatch(text):
        arguments = {"number": match[1]} if match[1] else {}
        return ParseResult(
            BusinessIntent("query", "purchase_orders", arguments, {}, 0.95, "local_rule")
        )
    clauses = _clauses(text)
    if not clauses or not 2 <= len(clauses) <= 4:
        return ParseResult(None, error="unsupported_local_text")
    purchase, price = PURCHASE.fullmatch(clauses[0]), PRICE.fullmatch(clauses[1])
    if not purchase or not price or (price[1] and price[1] != purchase[2]):
        return ParseResult(None, error="unsupported_local_text")
    product = _entity(purchase[3])
    if not product:
        return ParseResult(None, error="ambiguous_entity")
    values = {"商品": product, "数量": purchase[1], "单位": purchase[2], "单价": price[2]}
    for clause in clauses[2:]:
        match = re.fullmatch(r"(供应商|币种)\s*[=：:]\s*(.+)", clause)
        if not match or match[1] in values:
            return ParseResult(None, error="unsupported_local_text")
        value = _entity(match[2]) if match[1] == "供应商" else match[2].strip()
        if not value or (match[1] == "币种" and not re.fullmatch(r"[A-Z]{3}", value)):
            return ParseResult(None, error="unsupported_local_text")
        values[match[1]] = value
    parsed = parse_fixed_command(
        shlex.join(["/erp", "采购", "新增", *[k + "=" + v for k, v in values.items()]])
    )
    if parsed.intent:
        return replace(
            parsed, intent=replace(parsed.intent, parser_source="local_rule", confidence=0.9)
        )
    return parsed


def parse_message(text: str) -> ParseResult:
    # Never reinterpret a malformed command as a natural-language write.
    if isinstance(text, str) and text.strip().startswith("/"):
        return parse_fixed_command(text)
    return parse_local_text(text)
