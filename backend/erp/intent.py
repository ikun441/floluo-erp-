"""Protocol-independent fixed-command parser; parsing never authorizes or executes a business action."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

MAX_MESSAGE_LENGTH = 4096
MAX_AMOUNT = Decimal("9999999999999999.99")
MAX_QUANTITY = Decimal("99999999999999.9999")


@dataclass(frozen=True, slots=True)
class BusinessIntent:
    operation: Literal["query"] | Literal["create"]
    resource: Literal["inventory", "purchase_orders"]
    arguments: dict[str, str]
    references: dict[str, str]
    confidence: float
    parser_source: Literal["command", "local_rule"] = "command"


@dataclass(frozen=True, slots=True)
class ParseResult:
    intent: BusinessIntent | None
    missing: tuple[str, ...] = ()
    error: str | None = None


def _decimal(value: str, *, positive: bool, maximum: Decimal, places: int) -> bool:
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return False
    if not number.is_finite() or (number <= 0 if positive else number < 0) or number > maximum:
        return False
    try:
        return number == number.quantize(Decimal(1).scaleb(-places))
    except InvalidOperation:
        return False


def parse_fixed_command(text: str) -> ParseResult:
    """Parse the supported /erp grammar into an inert, validated intent."""
    if not isinstance(text, str) or not text or len(text) > MAX_MESSAGE_LENGTH:
        return ParseResult(None, error="invalid_message")
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        return ParseResult(None, error="invalid_quoting")
    if len(tokens) < 3 or tokens[:1] != ["/erp"]:
        return ParseResult(None, error="unsupported_command")
    domain, verb, *rest = tokens[1:]
    if domain == "库存" and verb == "查询":
        if not rest or len(rest) != 1 or not rest[0].strip():
            return ParseResult(None, error="invalid_arguments")
        return ParseResult(BusinessIntent("query", "inventory", {"query": rest[0]}, {}, 1.0))
    if domain == "采购" and verb == "查询":
        if len(rest) > 1:
            return ParseResult(None, error="invalid_arguments")
        args = {"number": rest[0]} if rest else {}
        return ParseResult(BusinessIntent("query", "purchase_orders", args, {}, 1.0))
    if domain != "采购" or verb != "新增":
        return ParseResult(None, error="unsupported_command")
    allowed = {
        "商品": "product",
        "数量": "quantity",
        "单价": "unit_price",
        "供应商": "supplier",
        "币种": "currency",
        "单位": "unit",
    }
    values: dict[str, str] = {}
    for token in rest:
        if "=" not in token:
            return ParseResult(None, error="invalid_arguments")
        key, value = token.split("=", 1)
        if key not in allowed or not value or allowed[key] in values:
            return ParseResult(None, error="invalid_arguments")
        values[allowed[key]] = value
    missing = tuple(
        key
        for key in ("product", "quantity", "unit_price", "supplier", "currency")
        if key not in values
    )
    if "quantity" in values and not _decimal(
        values["quantity"], positive=True, maximum=MAX_QUANTITY, places=4
    ):
        return ParseResult(None, error="invalid_quantity")
    if "unit_price" in values and not _decimal(
        values["unit_price"], positive=False, maximum=MAX_AMOUNT, places=2
    ):
        return ParseResult(None, error="invalid_unit_price")
    if "currency" in values and (
        len(values["currency"]) != 3
        or not values["currency"].isalpha()
        or not values["currency"].isascii()
    ):
        return ParseResult(None, error="invalid_currency")
    if "unit" in values and (len(values["unit"]) > 30 or not values["unit"].strip()):
        return ParseResult(None, error="invalid_unit")
    references = {key: values.pop(key) for key in ("product", "supplier") if key in values}
    return ParseResult(
        BusinessIntent("create", "purchase_orders", values, references, 1.0), missing
    )


PURCHASE_KEYS = {
    "product": "商品",
    "supplier": "供应商",
    "quantity": "数量",
    "unit_price": "单价",
    "currency": "币种",
    "unit": "单位",
}


def normalize_purchase_values(values):
    if not isinstance(values, dict) or not set(values) <= PURCHASE_KEYS.keys():
        raise ValueError("invalid_operation_values")
    if any(not isinstance(v, str) or not v.strip() or len(v) > 160 for v in values.values()):
        raise ValueError("invalid_operation_values")
    values = {k: v.strip() for k, v in values.items()}
    if "currency" in values and (
        not values["currency"].isascii() or not values["currency"].isupper()
    ):
        raise ValueError("invalid_operation_values")
    parsed = parse_fixed_command(
        shlex.join(
            ["/erp", "采购", "新增", *[PURCHASE_KEYS[k] + "=" + v for k, v in values.items()]]
        )
    )
    if parsed.intent is None:
        raise ValueError("invalid_operation_values")
    return values, list(parsed.missing)
