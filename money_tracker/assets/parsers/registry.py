"""Map parser ids to report parse functions and supported extensions.

Register your institution-specific parsers here. See docs/adding-parsers.md.
"""

from __future__ import annotations

import os
from typing import Any, Callable

ParserFn = Callable[[str], dict[str, Any] | None]

PARSERS: dict[str, ParserFn] = {}

PARSER_EXTENSIONS: dict[str, frozenset[str]] = {}

PARSER_LABELS: dict[str, str] = {}


def get_parser(parser_id: str) -> ParserFn | None:
    return PARSERS.get(str(parser_id))


def parser_accepts(parser_id: str, path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    allowed = PARSER_EXTENSIONS.get(str(parser_id))
    if allowed is None:
        return True
    return ext in allowed


def report_extensions() -> frozenset[str]:
    exts: set[str] = set()
    for values in PARSER_EXTENSIONS.values():
        exts.update(values)
    return frozenset(exts)


def parser_dropdown_options() -> list[dict[str, str]]:
    return [
        {"label": PARSER_LABELS.get(key, key), "value": key}
        for key in PARSERS
    ]
