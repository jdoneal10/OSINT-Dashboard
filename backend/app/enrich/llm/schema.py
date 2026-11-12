"""Convert a pydantic model into a strict JSON schema for ``output_config.format``.

Structured outputs require every object to set ``additionalProperties: false`` and list all
properties as required (optional fields are expressed as ``anyOf [..., null]``). Titles and
defaults are dropped. The response is still validated by the pydantic model itself.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

_DROP = {"title", "default", "examples"}


def _strict(node: Any) -> Any:
    if isinstance(node, dict):
        out = {k: _strict(v) for k, v in node.items() if k not in _DROP}
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
