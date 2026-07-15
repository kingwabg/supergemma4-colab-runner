"""Deterministic, resumable evaluation helpers for local language models."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.request import urlopen


TARGET_SCORE = 95.0


def _read_json(source: str | Path) -> Any:
    source_text = str(source)
    if source_text.startswith("https://"):
        with urlopen(source_text, timeout=30) as response:  # noqa: S310 - caller controls URL
            return json.loads(response.read().decode("utf-8"))
    return json.loads(Path(source).read_text(encoding="utf-8"))


def load_eval_cases(source: str | Path, min_cases: int = 50, max_cases: int = 100) -> list[dict[str, Any]]:
    """Load and validate a bounded work evaluation set."""

    payload = _read_json(source)
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("평가셋은 cases 배열 또는 배열 자체여야 합니다.")
    if not min_cases <= len(cases) <= max_cases:
        raise ValueError(f"평가 문항은 {min_cases}~{max_cases}개여야 합니다: {len(cases)}개")

    seen: set[str] = set()
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"{index}번 평가 문항이 객체가 아닙니다.")
        case_id = str(case.get("id", "")).strip()
        if not case_id or case_id in seen:
            raise ValueError(f"평가 문항 id가 없거나 중복입니다: {case_id!r}")
        seen.add(case_id)
        if not str(case.get("prompt", "")).strip():
            raise ValueError(f"{case_id}: prompt가 비어 있습니다.")
        grader = case.get("grader")
        if not isinstance(grader, dict) or not grader.get("type"):
            raise ValueError(f"{case_id}: grader.type이 필요합니다.")
    return cases


def _normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def _contains(text: str, needle: Any, case_sensitive: bool) -> bool:
    haystack = str(text)
    wanted = str(needle)
    if not case_sensitive:
        haystack, wanted = haystack.lower(), wanted.lower()
    return wanted in haystack


def score_answer(case: dict[str, Any], answer: str) -> tuple[bool, str]:
    """Score one answer with transparent deterministic rules."""

    grader = case["grader"]
    grader_type = str(grader.get("type", "")).lower()
    case_sensitive = bool(grader.get("case_sensitive", False))
    forbidden = [str(item) for item in grader.get("forbidden", [])]
    for item in forbidden:
        if _contains(answer, item, case_sensitive):
            return False, f"금지 문자열 포함: {item}"

    if grader_type == "exact":
        expected = str(grader.get("value", ""))
        actual = str(answer).strip() if case_sensitive else _normalize(answer)
        wanted = expected.strip() if case_sensitive else _normalize(expected)
        return actual == wanted, f"expected={expected!r}"

    if grader_type == "contains_all":
        values = list(grader.get("values", []))
        missing = [str(item) for item in values if not _contains(answer, item, case_sensitive)]
        return not missing, "누락=" + ", ".join(missing)

    if grader_type == "contains_any":
        values = list(grader.get("values", []))
        matched = [str(item) for item in values if _contains(answer, item, case_sensitive)]
        return bool(matched), "허용 표현 중 하나 필요=" + ", ".join(map(str, values))

    if grader_type == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = str(grader.get("pattern", ""))
        return bool(re.search(pattern, str(answer).strip(), flags=flags)), f"pattern={pattern}"

    if grader_type == "json_keys":
        try:
            parsed = json.loads(str(answer).strip())
        except json.JSONDecodeError as error:
            return False, f"JSON 해석 실패: {error.msg}"
        if not isinstance(parsed, dict):
            return False, "JSON 객체가 아닙니다."
        required = [str(item) for item in grader.get("keys", [])]
        missing = [key for key in required if key not in parsed]
        expected_values = grader.get("values", {})
        wrong = [key for key, value in expected_values.items() if parsed.get(key) != value]
        return not missing and not wrong, f"누락={missing}, 값 불일치={wrong}"

    if grader_type == "unknown":
        phrases = grader.get("values") or ["알 수 없", "정보가 없", "확인할 수 없", "모릅니다"]
        matched = any(_contains(answer, phrase, False) for phrase in phrases)
        return matched, "근거 부족을 명시해야 합니다."

    raise ValueError(f"지원하지 않는 grader.type: {grader_type}")


def _fingerprint(cases: Iterable[dict[str, Any]]) -> str:
    payload = json.dumps(list(cases), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _summarize(items: list[dict[str, Any]], selected_count: int) -> dict[str, Any]:
    passed = sum(bool(item.get("passed")) for item in items)
    total = len(items)
    by_category: dict[str, dict[str, Any]] = defaultdict(lambda: {"passed": 0, "total": 0})
    for item in items:
        category = str(item.get("category", "uncategorized"))
        by_category[category]["total"] += 1
        by_category[category]["passed"] += int(bool(item.get("passed")))
    for category in by_category.values():
        category["score"] = round(100 * category["passed"] / max(1, category["total"]), 1)

    target_passes = math.ceil(selected_count * TARGET_SCORE / 100)
    return {
        "score": round(100 * passed / max(1, total), 1),
        "passed": passed,
        "completed": total,
        "selected": selected_count,
        "target_score": TARGET_SCORE,
        "target_passes": target_passes,
        "remaining_to_target": max(0, target_passes - passed),
        "categories": dict(sorted(by_category.items())),
    }


def run_evaluation(
    generate: Callable[..., str],
    cases: list[dict[str, Any]],
    output_path: str | Path,
    *,
    run_id: str,
    categories: list[str] | None = None,
    limit: int | None = None,
    resume: bool = True,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run a checkpointed evaluation and return the full report."""

    selected = [case for case in cases if not categories or case.get("category") in categories]
    if limit is not None:
        selected = selected[: max(0, int(limit))]
    if not selected:
        raise ValueError("실행할 평가 문항이 없습니다.")

    output = Path(output_path)
    dataset_hash = _fingerprint(selected)
    items: list[dict[str, Any]] = []
    if resume and output.exists():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
            if previous.get("run_id") == run_id and previous.get("dataset_hash") == dataset_hash:
                items = list(previous.get("items", []))
        except (json.JSONDecodeError, OSError):
            items = []
    completed_ids = {str(item.get("id")) for item in items}

    started = time.time()
    report: dict[str, Any] = {
        "run_id": run_id,
        "dataset_hash": dataset_hash,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    for case in selected:
        if case["id"] in completed_ids:
            continue
        case_started = time.time()
        try:
            answer = generate(
                case["prompt"],
                max_tokens=int(case.get("max_tokens", 160)),
                temperature=0.0,
                use_thinking=bool(case.get("use_thinking", False)),
            )
            passed, detail = score_answer(case, answer)
            error = ""
        except Exception as exception:  # model/runtime failures are evaluation results
            answer = ""
            passed = False
            detail = "생성 오류"
            error = f"{type(exception).__name__}: {exception}"
        item = {
            "id": case["id"],
            "category": case.get("category", "uncategorized"),
            "passed": passed,
            "answer": answer,
            "detail": detail,
            "error": error,
            "seconds": round(time.time() - case_started, 2),
        }
        items.append(item)
        report["items"] = items
        report["summary"] = _summarize(items, len(selected))
        report["elapsed_seconds"] = round(time.time() - started, 2)
        _write_report(output, report)
        if on_result:
            on_result(item)

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["summary"] = _summarize(items, len(selected))
    report["elapsed_seconds"] = round(time.time() - started, 2)
    _write_report(output, report)
    return report
