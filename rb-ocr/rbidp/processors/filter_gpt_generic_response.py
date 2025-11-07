import os
import json
from typing import Any, Dict, Optional


def _try_parse_inner_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None


def _extract_from_openai_like(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    choices = obj.get("choices")
    if isinstance(choices, list) and choices:
        c0 = choices[0]
        if isinstance(c0, dict):
            msg = c0.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    inner = _try_parse_inner_json(content)
                    if isinstance(inner, dict):
                        return inner
            text = c0.get("text")
            if isinstance(text, str):
                inner = _try_parse_inner_json(text)
                if isinstance(inner, dict):
                    return inner
    # Some providers include direct top-level content
    content = obj.get("content")
    if isinstance(content, str):
        inner = _try_parse_inner_json(content)
        if isinstance(inner, dict):
            return inner
    return None


def filter_gpt_generic_response(input_path: str, output_dir: str, filename: str) -> str:
    """
    Generic GPT response filter that expects provider to write multiple JSON lines.
    Strategy per line:
      1) If dict: try to extract OpenAI-like inner JSON (choices[0].message.content). If found, use it.
      2) If dict: else use the dict as-is.
      3) If string: try to parse it as JSON dict.
    The first successful dict is written as the filtered output. If none found, write {}.
    """
    with open(input_path, "r", encoding="utf-8") as f:
        raw = f.read()

    result_obj: Dict[str, Any] = {}

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            # maybe a JSON string
            inner = _try_parse_inner_json(line)
            if isinstance(inner, dict):
                result_obj = inner
                break
            continue

        if isinstance(obj, dict):
            inner = _extract_from_openai_like(obj)
            if isinstance(inner, dict):
                result_obj = inner
                break
            # Skip provider prompt-echo dicts (they usually contain 'Model' and 'Content')
            if "Model" in obj and "Content" in obj:
                continue
            # Otherwise, accept the dict as-is
            result_obj = obj
            break
        elif isinstance(obj, str):
            inner = _try_parse_inner_json(obj)
            if isinstance(inner, dict):
                result_obj = inner
                break

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, filename)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result_obj, f, ensure_ascii=False, indent=2)
    return out_path
