import json
import logging
from pathlib import Path
from typing import Any


def setup_app_logger(log_file: str, logger_name: str = "travel_agent.api") -> logging.Logger:
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        root.addHandler(sh)

    resolved = str(log_path.resolve())
    if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == resolved for h in root.handlers):
        fh = logging.FileHandler(resolved, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)

    return logging.getLogger(logger_name)


def truncate_for_log(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...(truncated)"


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _find_first_key(payload: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(payload, dict):
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        for value in payload.values():
            found = _find_first_key(value, keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_first_key(value, keys)
            if found is not None:
                return found
    return None


def dump_item(item: Any) -> str:
    raw_item = getattr(item, "raw_item", None)
    if raw_item is not None:
        return _to_text(raw_item)
    return _to_text(getattr(item, "__dict__", str(item)))


def extract_tool_arguments(item: Any) -> str | None:
    candidate_keys = (
        "arguments",
        "arguments_json",
        "function_arguments",
        "args",
        "input",
        "input_json",
        "tool_input",
    )
    raw_item = getattr(item, "raw_item", None)
    if isinstance(raw_item, dict):
        found = _find_first_key(raw_item, candidate_keys)
        if found is not None:
            return _to_text(found)

    for key in candidate_keys:
        value = getattr(item, key, None)
        if value is not None:
            return _to_text(value)

    item_dict = getattr(item, "__dict__", None)
    if isinstance(item_dict, dict):
        found = _find_first_key(item_dict, candidate_keys)
        if found is not None:
            return _to_text(found)
    return None


def extract_tool_output(item: Any) -> str | None:
    raw_item = getattr(item, "raw_item", None)
    if isinstance(raw_item, dict):
        for key in ("output_text", "output", "result", "text", "content"):
            if key in raw_item and raw_item[key] is not None:
                return _to_text(raw_item[key])
        try:
            return json.dumps(raw_item, ensure_ascii=False)
        except Exception:
            return str(raw_item)

    for key in ("output_text", "output", "result", "text", "content"):
        value = getattr(item, key, None)
        if value is not None:
            return _to_text(value)
    return None
