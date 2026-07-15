"""Safe, checkpointed mini-repository evaluation for local coding agents.

The evaluator intentionally exposes a tiny tool protocol instead of passing grader
answers to the model.  Each task runs in a temporary workspace, public tests are
available to the agent, and hidden tests are mounted only after the agent finishes.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable
from urllib.request import urlopen


TARGET_SCORE = 95.0
CODEX_PROTOCOL_VERSION = "sentinel-plan-v1"
ALLOWED_SUFFIXES = {".py", ".json", ".md", ".txt", ".toml", ".yaml", ".yml"}
ALLOWED_IMPORT_ROOTS = {
    "collections",
    "dataclasses",
    "datetime",
    "decimal",
    "fractions",
    "functools",
    "itertools",
    "json",
    "math",
    "re",
    "statistics",
    "string",
    "typing",
}
DANGEROUS_CALLS = {"breakpoint", "compile", "eval", "exec", "input", "open", "__import__"}
DANGEROUS_ATTRIBUTE_ROOTS = {
    "ctypes",
    "httpx",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "urllib",
}


def _read_json(source: str | Path) -> Any:
    source_text = str(source)
    if source_text.startswith("https://"):
        with urlopen(source_text, timeout=30) as response:  # noqa: S310 - caller controls URL
            return json.loads(response.read().decode("utf-8"))
    return json.loads(Path(source).read_text(encoding="utf-8"))


def load_codex_cases(source: str | Path, min_cases: int = 1, max_cases: int = 100) -> list[dict[str, Any]]:
    """Load and validate repository tasks without exposing their hidden tests."""

    payload = _read_json(source)
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list) or not min_cases <= len(cases) <= max_cases:
        raise ValueError(f"Codex형 평가 문항은 {min_cases}~{max_cases}개여야 합니다.")

    seen: set[str] = set()
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"{index}번 문항이 객체가 아닙니다.")
        case_id = str(case.get("id", "")).strip()
        if not case_id or case_id in seen:
            raise ValueError(f"문항 id가 없거나 중복입니다: {case_id!r}")
        seen.add(case_id)
        if not str(case.get("instruction", "")).strip():
            raise ValueError(f"{case_id}: instruction이 비어 있습니다.")
        files = case.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError(f"{case_id}: files 객체가 필요합니다.")
        if not str(case.get("public_test", "")).strip() or not str(case.get("hidden_test", "")).strip():
            raise ValueError(f"{case_id}: public_test와 hidden_test가 필요합니다.")
        for relative_path in files:
            _safe_relative_path(relative_path)
    return cases


def _safe_relative_path(value: Any) -> PurePosixPath:
    text = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ValueError("작업공간 밖의 경로는 사용할 수 없습니다.")
    if any(part.startswith(".") for part in path.parts):
        raise ValueError("숨김 경로는 사용할 수 없습니다.")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"허용하지 않는 파일 형식입니다: {path.suffix}")
    return path


def _bounded(text: Any, limit: int = 12000) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n... ({len(value) - limit}자 생략)"


def _parse_action(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("JSON 도구 호출을 찾지 못했습니다.")
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict) or not isinstance(parsed.get("action"), str):
        raise ValueError("도구 호출에는 action 문자열이 필요합니다.")
    return parsed


def _python_policy_errors(workspace: Path) -> list[str]:
    errors: list[str] = []
    local_roots = {
        path.name
        for path in workspace.iterdir()
        if path.is_dir() and not path.name.startswith(".") and path.name != "tests"
    }
    local_roots.update(
        path.stem
        for path in workspace.glob("*.py")
        if not path.name.startswith(".")
    )
    for path in sorted(workspace.rglob("*.py")):
        relative = path.relative_to(workspace)
        if relative.parts[0] in {"tests", ".codex_eval"}:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        except (OSError, SyntaxError) as error:
            errors.append(f"{relative}: Python 구문 오류: {error}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root not in ALLOWED_IMPORT_ROOTS and root not in local_roots:
                        errors.append(f"{relative}:{node.lineno}: 허용하지 않는 import {root}")
            elif isinstance(node, ast.ImportFrom):
                root = str(node.module or "").split(".", 1)[0]
                if not node.level and root not in ALLOWED_IMPORT_ROOTS and root not in local_roots:
                    errors.append(f"{relative}:{node.lineno}: 허용하지 않는 import {root}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in DANGEROUS_CALLS:
                    errors.append(f"{relative}:{node.lineno}: 위험 호출 {node.func.id}")
            elif isinstance(node, ast.Attribute):
                root = node.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id in DANGEROUS_ATTRIBUTE_ROOTS:
                    errors.append(f"{relative}:{node.lineno}: 위험 객체 접근 {root.id}")
                if node.attr.startswith("__") and node.attr.endswith("__"):
                    errors.append(f"{relative}:{node.lineno}: dunder 속성 접근 금지")
    return errors


def _set_process_limits() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (48, 48))
    except (ImportError, OSError, ValueError):
        pass


def _run_test_file(workspace: Path, test_path: Path) -> dict[str, Any]:
    policy_errors = _python_policy_errors(workspace)
    if policy_errors:
        return {"passed": False, "output": "정책 검사 실패:\n" + "\n".join(policy_errors[:20]), "policy_blocked": True}
    started = time.time()
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-S", str(test_path)],
            cwd=workspace,
            text=True,
            capture_output=True,
            timeout=8,
            env={"PYTHONHASHSEED": "0", "PATH": os.environ.get("PATH", "")},
            preexec_fn=_set_process_limits if os.name == "posix" else None,
            check=False,
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        return {
            "passed": result.returncode == 0,
            "output": _bounded(output, 6000),
            "returncode": result.returncode,
            "seconds": round(time.time() - started, 2),
            "policy_blocked": False,
        }
    except subprocess.TimeoutExpired:
        return {"passed": False, "output": "테스트 제한 시간 8초 초과", "policy_blocked": False, "seconds": 8.0}


def _write_initial_workspace(workspace: Path, case: dict[str, Any]) -> None:
    for relative_path, content in case["files"].items():
        path = workspace / _safe_relative_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")
    test_dir = workspace / "tests"
    test_dir.mkdir(exist_ok=True)
    (test_dir / "test_public.py").write_text(str(case["public_test"]), encoding="utf-8")
    hidden_dir = workspace / ".codex_eval"
    hidden_dir.mkdir(exist_ok=True)
    (hidden_dir / "test_hidden.py").write_text(str(case["hidden_test"]), encoding="utf-8")


def _visible_tree(workspace: Path) -> list[str]:
    files = []
    for path in sorted(workspace.rglob("*")):
        if path.is_file() and ".codex_eval" not in path.parts:
            files.append(path.relative_to(workspace).as_posix())
    return files


AGENT_SYSTEM_PROMPT = """당신은 작은 저장소에서 실제 코드를 수정하는 코딩 에이전트입니다.
설명이나 코드 펜스를 붙이지 말고 아래 도구 형식만 출력하세요.
첫 행동은 요청에서 반환 타입, 허용값·별칭, 예외 조건, 보존 조건을 추출한 plan이어야 합니다.
허용 도구:
{"action":"plan","checklist":["검증할 명세 조건"]}
{"action":"inspect"}
{"action":"read_files","paths":["경로"]}
{"action":"run_tests"}
{"action":"finish","summary":"변경 요약","checklist_verified":true}
코드 파일 쓰기는 JSON 문자열 대신 다음 센티널 형식을 우선 사용하세요. 여러 파일 블록도 한 응답에 쓸 수 있습니다.
<<<WRITE_FILE app/example.py>>>
파일 전체 내용을 그대로 작성
<<<END_WRITE_FILE>>>
이 형식에서는 역슬래시와 줄바꿈을 JSON용으로 이스케이프하지 마세요. 기존 JSON write_files 형식도 호환됩니다.
작업공간 밖 접근, 셸 명령, 네트워크, 파일 삭제는 허용되지 않습니다.
요구사항에 필요한 최소 변경만 하고 공개 테스트를 실행한 뒤, plan 체크리스트를 다시 대조하고 완료하세요."""


WRITE_FILE_BLOCK = re.compile(
    r"^<<<WRITE_FILE ([^>\r\n]+)>>>\r?\n(.*?)^<<<END_WRITE_FILE>>>[ \t]*(?:\r?\n|$)",
    flags=re.MULTILINE | re.DOTALL,
)


def _parse_codex_action(raw: str) -> dict[str, Any]:
    """Parse JSON metadata actions or code-preserving sentinel file blocks."""

    text = str(raw or "").strip()
    if "<<<WRITE_FILE " not in text:
        return _parse_action(text)
    matches = list(WRITE_FILE_BLOCK.finditer(text + ("\n" if not text.endswith("\n") else "")))
    if not matches:
        raise ValueError("WRITE_FILE 센티널 블록 형식이 올바르지 않습니다.")
    cursor = 0
    files: dict[str, str] = {}
    parsed_text = text + ("\n" if not text.endswith("\n") else "")
    for match in matches:
        if parsed_text[cursor : match.start()].strip():
            raise ValueError("WRITE_FILE 블록 밖에는 설명을 쓸 수 없습니다.")
        relative = match.group(1).strip()
        if relative in files:
            raise ValueError(f"같은 파일 블록이 중복됐습니다: {relative}")
        files[relative] = match.group(2)
        cursor = match.end()
    if parsed_text[cursor:].strip():
        raise ValueError("WRITE_FILE 블록 밖에는 설명을 쓸 수 없습니다.")
    return {"action": "write_files", "files": files, "format": "sentinel"}


def _execute_action(workspace: Path, action: dict[str, Any], state: dict[str, Any]) -> tuple[str, bool, bool]:
    name = str(action.get("action", "")).strip().lower()
    if name == "plan":
        checklist = action.get("checklist")
        if not isinstance(checklist, list) or not 1 <= len(checklist) <= 12:
            raise ValueError("plan에는 1~12개의 checklist 배열이 필요합니다.")
        normalized = [str(item).strip() for item in checklist if str(item).strip()]
        if not normalized:
            raise ValueError("plan checklist가 비어 있습니다.")
        state["checklist"] = normalized
        return "명세 체크리스트 저장 완료:\n- " + "\n- ".join(normalized), False, False
    if name == "inspect":
        chunks = []
        for relative in _visible_tree(workspace):
            path = workspace / relative
            chunks.append(f"--- {relative} ---\n{_bounded(path.read_text(encoding='utf-8'), 5000)}")
        return _bounded("\n".join(chunks), 14000), False, False
    if name == "read_files":
        paths = action.get("paths")
        if not isinstance(paths, list) or not paths:
            raise ValueError("read_files에는 paths 배열이 필요합니다.")
        chunks = []
        for item in paths[:8]:
            relative = _safe_relative_path(item)
            path = workspace / relative
            if not path.is_file() or ".codex_eval" in path.parts:
                raise ValueError(f"읽을 수 없는 파일입니다: {relative}")
            chunks.append(f"--- {relative} ---\n{_bounded(path.read_text(encoding='utf-8'), 6000)}")
        return _bounded("\n".join(chunks), 14000), False, False
    if name == "write_files":
        if state.get("require_plan") and not state.get("checklist"):
            raise ValueError("코드를 쓰기 전에 plan 체크리스트를 먼저 제출하세요.")
        files = action.get("files")
        if not isinstance(files, dict) or not files or len(files) > 8:
            raise ValueError("write_files에는 1~8개의 files 객체가 필요합니다.")
        written = []
        for relative_text, content in files.items():
            relative = _safe_relative_path(relative_text)
            if relative.parts[0] == "tests":
                raise ValueError("평가 테스트 파일은 수정할 수 없습니다.")
            if not isinstance(content, str) or len(content) > 20000:
                raise ValueError(f"파일 내용이 문자열이 아니거나 너무 큽니다: {relative}")
            path = workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written.append(relative.as_posix())
        policy_errors = _python_policy_errors(workspace)
        if policy_errors:
            return "파일은 저장했지만 정책 검사를 통과하지 못했습니다:\n" + "\n".join(policy_errors[:20]), False, True
        return "저장 완료: " + ", ".join(written), False, False
    if name == "run_tests":
        if state.get("require_plan") and not state.get("checklist"):
            raise ValueError("테스트 전에 plan 체크리스트를 먼저 제출하세요.")
        result = _run_test_file(workspace, workspace / "tests" / "test_public.py")
        state["public_test_runs"] = int(state.get("public_test_runs", 0)) + 1
        state["last_public_test_passed"] = bool(result["passed"])
        label = "공개 테스트 통과" if result["passed"] else "공개 테스트 실패"
        return f"{label}\n{result['output']}", False, bool(result.get("policy_blocked"))
    if name == "finish":
        if state.get("require_plan") and not state.get("checklist"):
            raise ValueError("finish 전에 plan 체크리스트를 제출하세요.")
        if state.get("require_plan") and action.get("checklist_verified") is not True:
            raise ValueError("finish에는 plan을 다시 대조했다는 checklist_verified=true가 필요합니다.")
        return _bounded(action.get("summary", "완료"), 1000), True, False
    raise ValueError(f"허용하지 않는 action입니다: {name!r}")


def run_codex_task(
    generate_action: Callable[..., str],
    case: dict[str, Any],
    *,
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run one isolated repository task and grade it with a hidden test."""

    started = time.time()
    max_steps = max(2, min(int(case.get("max_steps", 6)), 10))
    transcript: list[dict[str, str]] = []
    protocol_errors = 0
    policy_blocks = 0
    finished = False
    state: dict[str, Any] = {
        "require_plan": bool(case.get("require_plan", False)),
        "checklist": [],
        "public_test_runs": 0,
        "last_public_test_passed": False,
    }

    with tempfile.TemporaryDirectory(prefix=f"supergemma-{case['id'].lower()}-") as directory:
        workspace = Path(directory)
        _write_initial_workspace(workspace, case)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"작업 ID: {case['id']}\n범주: {case.get('category', 'uncategorized')}\n"
                    f"요청:\n{case['instruction']}\n\n현재 파일 목록:\n"
                    + "\n".join(_visible_tree(workspace))
                ),
            },
        ]
        for step_number in range(1, max_steps + 1):
            prompt_chars = sum(len(str(message.get("content", ""))) for message in messages)
            generation_options: dict[str, Any] = {
                "max_tokens": int(case.get("max_tokens", 900)),
                "temperature": 0.0,
                "use_thinking": True,
            }
            if state.get("require_plan") and not state.get("checklist"):
                generation_options["response_format"] = {"type": "json_object"}
            raw = generate_action(
                messages,
                **generation_options,
            )
            step: dict[str, Any] = {
                "step": step_number,
                "raw": _bounded(raw, 3000),
                "prompt_chars": prompt_chars,
                "response_chars": len(str(raw or "")),
            }
            messages.append({"role": "assistant", "content": str(raw)})
            try:
                action = _parse_codex_action(raw)
                step["action"] = action.get("action", "")
                step["format"] = action.get("format", "json")
                tool_result, finished, policy_blocked = _execute_action(workspace, action, state)
                policy_blocks += int(policy_blocked)
            except Exception as error:
                protocol_errors += 1
                step["action"] = "protocol_error"
                tool_result = f"도구 호출 오류: {type(error).__name__}: {error}. JSON 형식을 고쳐 다시 호출하세요."
            step["result"] = _bounded(tool_result, 4000)
            transcript.append(step)
            if on_step:
                on_step({"id": case["id"], **step})
            if finished:
                break
            messages.append({"role": "user", "content": "도구 결과:\n" + _bounded(tool_result, 6000)})

        hidden_result = _run_test_file(workspace, workspace / ".codex_eval" / "test_hidden.py")
        public_result = _run_test_file(workspace, workspace / "tests" / "test_public.py")
        changed_files = []
        for relative, original in case["files"].items():
            path = workspace / _safe_relative_path(relative)
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != str(original):
                changed_files.append(relative)

    strict_passed = bool(finished and hidden_result["passed"] and protocol_errors <= 1 and policy_blocks == 0)
    auto_submitted = bool(not finished and len(transcript) >= max_steps)
    system_track_passed = bool(
        (finished or auto_submitted)
        and hidden_result["passed"]
        and protocol_errors <= 1
        and policy_blocks == 0
    )
    return {
        "id": case["id"],
        "category": case.get("category", "uncategorized"),
        "title": case.get("title", ""),
        "passed": strict_passed,
        "strict_track_passed": strict_passed,
        "system_track_passed": system_track_passed,
        "auto_submitted": auto_submitted,
        "finished": finished,
        "hidden_tests_passed": bool(hidden_result["passed"]),
        "public_tests_passed": bool(public_result["passed"]),
        "protocol_errors": protocol_errors,
        "policy_blocks": policy_blocks,
        "steps": len(transcript),
        "checklist": list(state.get("checklist", [])),
        "public_test_runs": int(state.get("public_test_runs", 0)),
        "max_prompt_chars": max((int(step.get("prompt_chars", 0)) for step in transcript), default=0),
        "sentinel_writes": sum(step.get("action") == "write_files" and step.get("format") == "sentinel" for step in transcript),
        "json_writes": sum(step.get("action") == "write_files" and step.get("format") == "json" for step in transcript),
        "changed_files": changed_files,
        "hidden_output": _bounded(hidden_result["output"], 3000),
        "public_output": _bounded(public_result["output"], 3000),
        "transcript": transcript,
        "seconds": round(time.time() - started, 2),
    }


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
    system_passed = sum(bool(item.get("system_track_passed", item.get("passed"))) for item in items)
    hidden_passed = sum(bool(item.get("hidden_tests_passed")) for item in items)
    protocol_clean = sum(int(item.get("protocol_errors", 0)) == 0 for item in items)
    by_category: dict[str, dict[str, Any]] = defaultdict(lambda: {"passed": 0, "system_passed": 0, "total": 0})
    for item in items:
        category = str(item.get("category", "uncategorized"))
        by_category[category]["total"] += 1
        by_category[category]["passed"] += int(bool(item.get("passed")))
        by_category[category]["system_passed"] += int(bool(item.get("system_track_passed", item.get("passed"))))
    for result in by_category.values():
        result["score"] = round(100 * result["passed"] / max(1, result["total"]), 1)
        result["system_score"] = round(100 * result["system_passed"] / max(1, result["total"]), 1)
    target_passes = math.ceil(selected_count * TARGET_SCORE / 100)
    total = len(items)
    return {
        "score": round(100 * passed / max(1, total), 1),
        "passed": passed,
        "system_score": round(100 * system_passed / max(1, total), 1),
        "system_passed": system_passed,
        "auto_submit_recoveries": sum(
            bool(item.get("system_track_passed")) and not bool(item.get("strict_track_passed", item.get("passed")))
            for item in items
        ),
        "completed": total,
        "selected": selected_count,
        "target_score": TARGET_SCORE,
        "target_passes": target_passes,
        "remaining_to_target": max(0, target_passes - passed),
        "hidden_test_rate": round(100 * hidden_passed / max(1, total), 1),
        "protocol_compliance_rate": round(100 * protocol_clean / max(1, total), 1),
        "policy_blocks": sum(int(item.get("policy_blocks", 0)) for item in items),
        "average_steps": round(sum(int(item.get("steps", 0)) for item in items) / max(1, total), 2),
        "average_max_prompt_chars": round(sum(int(item.get("max_prompt_chars", 0)) for item in items) / max(1, total), 1),
        "max_prompt_chars": max((int(item.get("max_prompt_chars", 0)) for item in items), default=0),
        "sentinel_writes": sum(int(item.get("sentinel_writes", 0)) for item in items),
        "json_writes": sum(int(item.get("json_writes", 0)) for item in items),
        "categories": dict(sorted(by_category.items())),
    }


def _summary_only_item(item: dict[str, Any]) -> dict[str, Any]:
    """Keep checkpoint and aggregate fields without leaking held-out failure details."""

    allowed = {
        "id", "category", "title", "passed", "strict_track_passed", "system_track_passed",
        "auto_submitted", "finished", "hidden_tests_passed", "public_tests_passed",
        "protocol_errors", "policy_blocks", "steps", "seconds", "public_test_runs",
        "max_prompt_chars", "sentinel_writes", "json_writes",
    }
    return {key: value for key, value in item.items() if key in allowed}


def run_codex_evaluation(
    generate_action: Callable[..., str],
    cases: list[dict[str, Any]],
    output_path: str | Path,
    *,
    run_id: str,
    categories: list[str] | None = None,
    limit: int | None = None,
    resume: bool = True,
    store_details: bool = True,
    on_result: Callable[[dict[str, Any]], None] | None = None,
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run repository tasks with per-task checkpoints and deterministic grading."""

    selected = [case for case in cases if not categories or case.get("category") in categories]
    if limit is not None:
        selected = selected[: max(0, int(limit))]
    if not selected:
        raise ValueError("실행할 Codex형 평가 문항이 없습니다.")

    output = Path(output_path)
    dataset_hash = _fingerprint(selected)
    items: list[dict[str, Any]] = []
    if resume and output.exists():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
            if (
                previous.get("run_id") == run_id
                and previous.get("dataset_hash") == dataset_hash
                and bool(previous.get("store_details", True)) == bool(store_details)
            ):
                items = list(previous.get("items", []))
        except (json.JSONDecodeError, OSError):
            items = []
    completed_ids = {str(item.get("id")) for item in items}
    started = time.time()
    report: dict[str, Any] = {
        "run_id": run_id,
        "protocol_version": CODEX_PROTOCOL_VERSION,
        "store_details": bool(store_details),
        "dataset_hash": dataset_hash,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    for case in selected:
        if case["id"] in completed_ids:
            continue
        try:
            item = run_codex_task(generate_action, case, on_step=on_step)
        except Exception as error:
            item = {
                "id": case["id"],
                "category": case.get("category", "uncategorized"),
                "title": case.get("title", ""),
                "passed": False,
                "error": f"{type(error).__name__}: {error}",
                "seconds": 0.0,
                "steps": 0,
                "protocol_errors": 0,
                "policy_blocks": 0,
            }
        stored_item = item if store_details else _summary_only_item(item)
        items.append(stored_item)
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


def run_codex_repeated_evaluation(
    generate_action: Callable[..., str],
    cases: list[dict[str, Any]],
    output_path: str | Path,
    *,
    run_id: str,
    repeats: int = 1,
    categories: list[str] | None = None,
    limit: int | None = None,
    resume: bool = True,
    store_details: bool = True,
    on_result: Callable[[dict[str, Any]], None] | None = None,
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run independent repeats and report strict/system mean and dispersion."""

    repeat_count = max(1, min(int(repeats), 5))
    base = Path(output_path)
    reports: list[dict[str, Any]] = []
    run_paths: list[str] = []
    for index in range(1, repeat_count + 1):
        if repeat_count == 1:
            current_path = base
            current_run_id = run_id
        else:
            current_path = base.with_name(f"{base.stem}-r{index}{base.suffix}")
            current_run_id = f"{run_id}:r{index}"
        report = run_codex_evaluation(
            generate_action,
            cases,
            current_path,
            run_id=current_run_id,
            categories=categories,
            limit=limit,
            resume=resume,
            store_details=store_details,
            on_result=on_result,
            on_step=on_step,
        )
        reports.append(report)
        run_paths.append(str(current_path))

    strict_scores = [float(report["summary"]["score"]) for report in reports]
    system_scores = [float(report["summary"]["system_score"]) for report in reports]
    aggregate = {
        "repeats": repeat_count,
        "strict_score_mean": round(statistics.mean(strict_scores), 2),
        "strict_score_stddev": round(statistics.pstdev(strict_scores), 2),
        "strict_score_min": min(strict_scores),
        "strict_score_max": max(strict_scores),
        "system_score_mean": round(statistics.mean(system_scores), 2),
        "system_score_stddev": round(statistics.pstdev(system_scores), 2),
        "system_score_min": min(system_scores),
        "system_score_max": max(system_scores),
    }
    aggregate_path = None
    if repeat_count > 1:
        aggregate_output = base.with_name(f"{base.stem}-aggregate{base.suffix}")
        _write_report(
            aggregate_output,
            {
                "run_id": run_id,
                "aggregate": aggregate,
                "runs": [
                    {"path": path, "summary": report["summary"]}
                    for path, report in zip(run_paths, reports)
                ],
            },
        )
        aggregate_path = str(aggregate_output)
    return {"reports": reports, "aggregate": aggregate, "aggregate_path": aggregate_path}
