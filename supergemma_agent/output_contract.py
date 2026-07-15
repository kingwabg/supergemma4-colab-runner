"""Small deterministic tools for arithmetic and explicit output contracts."""

from __future__ import annotations

import json
import math
import re
from typing import Any


def _number(value: str) -> float:
    return float(value.replace(",", ""))


def _format_number(value: float) -> str:
    if math.isclose(value, round(value), abs_tol=1e-9):
        return str(int(round(value)))
    return f"{value:.10f}".rstrip("0").rstrip(".")


def solve_simple_math(prompt: str) -> str | None:
    """Solve a conservative set of unambiguous arithmetic word patterns."""

    text = re.sub(r"\s+", " ", str(prompt)).strip()

    weighted = re.search(
        r"([\d,.]+)\s*점이\s*([\d.]+)\s*%.*?([\d,.]+)\s*점이\s*([\d.]+)\s*%.*?가중\s*평균",
        text,
    )
    if weighted:
        first, first_weight, second, second_weight = map(_number, weighted.groups())
        total_weight = first_weight + second_weight
        if total_weight > 0:
            return _format_number((first * first_weight + second * second_weight) / total_weight)

    discount = re.search(r"([\d,.]+)\s*원에서\s*([\d.]+)\s*%\s*할인", text)
    if discount:
        price, percent = map(_number, discount.groups())
        return _format_number(price * (1 - percent / 100))

    percent_of = re.search(r"([\d,.]+)\s*의\s*([\d.]+)\s*%", text)
    if percent_of:
        value, percent = map(_number, percent_of.groups())
        return _format_number(value * percent / 100)

    multiply = re.search(r"([\d,.]+)\s*(?:곱하기|×)\s*([\d,.]+)", text)
    if multiply:
        left, right = map(_number, multiply.groups())
        return _format_number(left * right)

    repeated_increase = re.search(
        r"([\d,.]+).*?두\s*번\s*연속.*?각각\s*([\d.]+)\s*%\s*증가",
        text,
    )
    if repeated_increase:
        value, percent = map(_number, repeated_increase.groups())
        return _format_number(value * (1 + percent / 100) ** 2)

    return None


def _strip_code_fence(answer: str) -> str:
    match = re.fullmatch(r"\s*```(?:[\w.+-]+)?\s*\n?(.*?)\n?```\s*", answer, flags=re.DOTALL)
    return match.group(1).strip() if match else answer.strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _requested_line_values(prompt: str) -> list[str]:
    line_words = {"두": 2, "세": 3, "네": 4}
    line_match = re.search(r"정확히\s*(두|세|네|\d+)\s*줄", prompt)
    if not line_match or ":" not in prompt:
        return []
    token = line_match.group(1)
    count = line_words.get(token, int(token) if token.isdigit() else 0)
    tail = prompt.rsplit(":", 1)[-1].strip().rstrip(".")
    values = [item.strip() for item in re.split(r"\s*,\s*", tail) if item.strip()]
    return values if len(values) == count else []


def normalize_output(prompt: str, answer: str) -> str:
    """Enforce only formats explicitly requested in the user's prompt."""

    request = str(prompt)
    cleaned = _strip_code_fence(str(answer or ""))

    if re.search(r"JSON", request, flags=re.IGNORECASE) and ("객체" in request or "JSON만" in request):
        parsed = _extract_json_object(cleaned)
        if parsed is not None:
            return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))

    requested_lines = _requested_line_values(request)
    if requested_lines:
        actual_lines = [line for line in cleaned.splitlines() if line.strip()]
        if len(actual_lines) != len(requested_lines):
            return "\n".join(requested_lines)

    if "숫자로만" in request or "숫자만" in request:
        if re.fullmatch(r"[+-]?\d[\d,]*(?:\.\d+)?", cleaned):
            return cleaned.replace(",", "")

    if "명령만" in request or "명령을 정확히 한 줄" in request:
        command_lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        for line in command_lines:
            if re.match(r"^(?:git|curl|find|python|python3|npm|npx|pip|ls|cd)\b", line):
                return line

    if ("모르면 모른다고" in request or "문맥에 없으면 모른다고" in request) and cleaned in {
        "모른다고 답하세요",
        "모른다고 답하세요.",
    }:
        return "모릅니다."

    return cleaned
