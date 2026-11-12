"""Convert a pydantic model into a strict JSON schema for ``output_config.format``.

Structured outputs require every object to set ``additionalProperties: false`` and list all
properties as required (optional fields are expressed as ``anyOf [..., null]``). Titles and
defaults are dropped. Numeric and length constraints the API does not accept (``minimum``,
``maxLength``, ``maxItems`` ...) are moved into the field description as a hint; the pydantic
model still enforces them on the response (a violation is retried, then quarantined).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

_DROP = {"title", "default", "examples"}
# Constraints unsupported by structured outputs (minItems is kept only for 0 or 1).
_HINT = {
    "minimum": ">=",
    "maximum": "<=",
    "exclusiveMinimum": ">",
    "exclusiveMaximum": "<",
    "multipleOf": "multiple of",
    "minLength": "min length",
    "maxLength": "max length",
    "maxItems": "at most items:",
}


def _strict(node: Any) -> Any:
    if isinstance(node, dict):
        hints = [f"{_HINT[k]} {v}" for k, v in node.items() if k in _HINT]
        if node.get("minItems", 0) > 1:
            hints.append(f"at least items: {node['minItems']}")
        out = {
            k: _strict(v)
            for k, v in node.items()
            if k not in _DROP and k not in _HINT and not (k == "minItems" and v > 1)
        }
        if hints:
            desc = out.get("description")
            note = f"({'; '.join(hints)})"
            out["description"] = f"{desc} {note}" if desc else note
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out
    if isinstance(node, list):
        return [_strict(v) for v in node]
    return node


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema: dict[str, Any] = _strict(model.model_json_schema())
    return schema
