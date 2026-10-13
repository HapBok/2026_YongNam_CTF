"""Strict subset of JSON Schema used identically for CLI output and local validation."""
from .common import read_json, strict_json


def validate(value, schema, path="$"):
    types = {"object": dict, "array": list, "string": str, "integer": int,
             "number": (int, float), "boolean": bool, "null": type(None)}
    expected = schema.get("type")
    if expected:
        choices = expected if isinstance(expected, list) else [expected]
        if not any(isinstance(value, types[t]) and not (t in {"integer", "number"} and isinstance(value, bool)) for t in choices):
            raise ValueError(f"{path}: wrong type")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: invalid enum")
    if isinstance(value, dict):
        if set(schema.get("required", [])) - value.keys():
            raise ValueError(f"{path}: required field missing")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and value.keys() - props.keys():
            raise ValueError(f"{path}: unknown field")
        for k, v in value.items():
            if k in props:
                validate(v, props[k], path + "." + k)
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", 10000):
            raise ValueError(f"{path}: too many items")
        for i, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{i}]")
    if isinstance(value, str) and len(value) > schema.get("maxLength", 100000):
        raise ValueError(f"{path}: string too long")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            raise ValueError(f"{path}: out of bounds")


def handoff(data, root, task):
    value = strict_json(data)
    validate(value, read_json(root / "schemas/handoff.schema.json"))
    for k in ("challenge_id", "task_id", "generation"):
        if value[k] != task[k]:
            raise ValueError("HANDOFF_IDENTITY_MISMATCH")
    for fact in value["verified_facts"]:
        if not fact["evidence_path"] and not fact["repro_command"]:
            raise ValueError("FACT_WITHOUT_EVIDENCE")
    return value
