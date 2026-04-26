"""Small YAML subset parser for harness-owned fenced config blocks."""

from __future__ import annotations

import re
from typing import Any


class YamlBlockParseError(ValueError):
    """Raised when a harness YAML subset block cannot be parsed."""


def strip_comment(text: str) -> str:
    if " #" in text:
        return text.split(" #", 1)[0].rstrip()
    return text


def parse_scalar(value: str) -> Any:
    value = strip_comment(value.strip())
    if value == "":
        return ""
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if value in {"true", "false"}:
        return value == "true"
    if value in {"null", "~"}:
        return None
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def parse_yaml_block(text: str) -> Any:
    """Parse the minimal YAML subset used by harness markdown config blocks."""

    lines = text.splitlines()

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        result_dict: dict[str, Any] = {}
        result_list: list[Any] | None = None

        while index < len(lines):
            raw_line = lines[index]
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                index += 1
                continue

            current_indent = len(raw_line) - len(raw_line.lstrip(" "))
            if current_indent < indent:
                break
            if current_indent > indent:
                raise YamlBlockParseError(f"Unexpected indentation near line: {raw_line}")

            stripped = raw_line.strip()
            if stripped.startswith("- "):
                if result_dict:
                    raise YamlBlockParseError("Cannot mix mapping and list at same indentation.")
                if result_list is None:
                    result_list = []

                item_text = stripped[2:].strip()
                if item_text == "":
                    item, index = parse_block(index + 1, indent + 2)
                    result_list.append(item)
                    continue

                if ":" in item_text:
                    key, rest = item_text.split(":", 1)
                    key = key.strip()
                    rest = rest.strip()
                    item_map: dict[str, Any] = {}
                    if rest:
                        item_map[key] = parse_scalar(rest)
                        index += 1
                    else:
                        nested, index = parse_block(index + 1, indent + 2)
                        item_map[key] = nested

                    while index < len(lines):
                        next_line = lines[index]
                        if not next_line.strip() or next_line.lstrip().startswith("#"):
                            index += 1
                            continue
                        next_indent = len(next_line) - len(next_line.lstrip(" "))
                        if next_indent <= indent:
                            break
                        if next_indent != indent + 2:
                            raise YamlBlockParseError(f"Unexpected list item indentation near line: {next_line}")
                        nested_stripped = next_line.strip()
                        if nested_stripped.startswith("- "):
                            break
                        if ":" not in nested_stripped:
                            raise YamlBlockParseError(f"Malformed mapping line: {next_line}")
                        nested_key, nested_rest = nested_stripped.split(":", 1)
                        nested_key = nested_key.strip()
                        nested_rest = nested_rest.strip()
                        if nested_rest:
                            item_map[nested_key] = parse_scalar(nested_rest)
                            index += 1
                        else:
                            nested_value, index = parse_block(index + 1, indent + 4)
                            item_map[nested_key] = nested_value
                    result_list.append(item_map)
                    continue

                result_list.append(parse_scalar(item_text))
                index += 1
                continue

            if result_list is not None:
                raise YamlBlockParseError("Cannot mix list and mapping at same indentation.")
            if ":" not in stripped:
                raise YamlBlockParseError(f"Malformed mapping line: {raw_line}")
            key, rest = stripped.split(":", 1)
            key = key.strip()
            rest = rest.strip()
            if rest:
                result_dict[key] = parse_scalar(rest)
                index += 1
            else:
                nested, index = parse_block(index + 1, indent + 2)
                result_dict[key] = nested

        return (result_list if result_list is not None else result_dict), index

    parsed, _ = parse_block(0, 0)
    return parsed
