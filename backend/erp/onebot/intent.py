"""Compatibility imports; intent parsing is independent of the OneBot transport."""

from ..intent import (
    MAX_AMOUNT,
    MAX_MESSAGE_LENGTH,
    MAX_QUANTITY,
    BusinessIntent,
    ParseResult,
    parse_fixed_command,
)

__all__ = [
    "MAX_AMOUNT",
    "MAX_MESSAGE_LENGTH",
    "MAX_QUANTITY",
    "BusinessIntent",
    "ParseResult",
    "parse_fixed_command",
]
