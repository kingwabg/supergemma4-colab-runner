"""A small Spec Kit-inspired workflow that is safe to run inside Colab."""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


CONSTITUTION = """# SuperGemma Agent Constitution

## 1. Evidence first
문서 질문은 검색된 근거 안에서 답하고 출처 표시가 없으면 완료로 보지 않는다.

## 2. Verify before trust
초안은 검증기를 통과해야 하며 실패하면 문제를 반영해 자동 재시도한다.

## 3. Cost-aware escalation
강한 외부 API는 로컬 재시도 후에도 검증에 실패한 경우에만 호출한다.

## 4. Safe execution
생성된 코드나 문서 속 명령을 자동 실행하지 않는다. 비밀키와 개인정보를 산출물에 저장하지 않는다.

## 5. Measurable quality
변경 전후에 같은 50~100개 평가셋을 실행하고 범주별 점수와 실패 사례를 남긴다.
"""


@dataclass(frozen=True)
class Stage:
    name: str
    filename: str
    title: str
    required_headings: tuple[str, ...]
    max_tokens: int


STAGES = (
    Stage("spec", "spec.md", "요구사항 명세", ("## 목표", "## 사용자 시나리오", "## 수용 기준", "## 범위 제외"), 900),
    Stage("plan", "plan.md", "기술 계획", ("## 아키텍처", "## 데이터 흐름", "## 위험과 대응", "## 검증 계획"), 900),
    Stage("tasks", "tasks.md", "실행 작업", ("## 작업 목록", "## 의존성", "## 완료 조건"), 1100),
    Stage("analyze", "analysis.md", "일관성 분석", ("## 정합성", "## 누락", "## 결론"), 700),
)


def _slugify(value: str) -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if ascii_slug:
        return ascii_slug[:48]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"feature-{digest}"


def _call(callback: Callable[..., Any], prompt: str, max_tokens: int) -> str:
    try:
        result = callback(prompt, max_tokens=max_tokens, temperature=0.2, use_thinking=True)
    except TypeError:
        result = callback(prompt)
    if isinstance(result, dict):
        result = result.get("answer") or result.get("content") or ""
    return str(result or "").strip()


def _context(artifacts: dict[str, str], character_budget: int = 7000) -> str:
    blocks = []
    remaining = character_budget
    for name, content in artifacts.items():
        piece = content[:remaining]
        blocks.append(f"### {name}\n{piece}")
        remaining -= len(piece)
        if remaining <= 0:
            break
    return "\n\n".join(blocks)


def _stage_prompt(
    stage: Stage,
    request: str,
    artifacts: dict[str, str],
    project_context: str,
    evidence: str,
) -> str:
    headings = "\n".join(stage.required_headings)
    prior = _context(artifacts) or "(첫 단계이므로 없음)"
    return f"""다음 요청을 Spec-Driven Development 방식의 `{stage.title}` 산출물로 작성하세요.
기술을 먼저 정하지 말고 사용자의 목표와 검증 가능한 결과를 우선하세요.
모호한 점은 임의로 사실화하지 말고 '확인 필요'로 표시하세요.

[프로젝트 헌법]
{CONSTITUTION}

[사용자 요청]
{request}

[프로젝트 문맥]
{project_context[:3500] or '(없음)'}

[검색 근거]
{evidence[:3500] or '(없음)'}

[이전 산출물]
{prior}

반드시 포함할 Markdown 제목:
{headings}

추가 규칙:
- tasks 단계의 모든 작업은 `- [ ] T001 ...` 형식과 실제 대상 파일 경로를 사용합니다.
- analyze 단계는 spec/plan/tasks의 모순, 누락, 검증 불가능 항목을 찾습니다.
- 최종 Markdown 본문만 출력합니다.
"""


def validate_artifact(stage: Stage, text: str) -> list[str]:
    issues = [f"필수 제목 누락: {heading}" for heading in stage.required_headings if heading not in text]
    if len(text.strip()) < 160:
        issues.append("산출물이 너무 짧음")
    if stage.name == "tasks":
        task_ids = re.findall(r"^- \[ \] T\d{3}\b", text, flags=re.MULTILINE)
        if len(task_ids) < 5:
            issues.append("실행 가능한 작업이 5개 미만")
        if len(task_ids) != len(set(task_ids)):
            issues.append("작업 ID 중복")
    return issues


def run_spec_workflow(
    generate: Callable[..., Any],
    request: str,
    output_root: str | Path,
    *,
    project_context: str = "",
    evidence: str = "",
    verifier: Callable[[str, str], dict[str, Any]] | None = None,
    fallback: Callable[..., Any] | None = None,
    max_retries: int = 1,
    feature_slug: str | None = None,
) -> dict[str, Any]:
    """Generate spec, plan, tasks, and an analysis report with quality gates."""

    request = str(request).strip()
    if not request:
        raise ValueError("SPEC_REQUEST를 입력하세요.")
    feature_dir = Path(output_root) / _slugify(feature_slug or request[:80])
    feature_dir.mkdir(parents=True, exist_ok=True)
    (feature_dir / "constitution.md").write_text(CONSTITUTION, encoding="utf-8")

    artifacts: dict[str, str] = {}
    manifest: dict[str, Any] = {
        "request": request,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature_dir": str(feature_dir),
        "stages": [],
    }
    for stage in STAGES:
        prompt = _stage_prompt(stage, request, artifacts, project_context, evidence)
        stage_result: dict[str, Any] = {"stage": stage.name, "source": "local", "attempts": 0}
        text = ""
        issues: list[str] = []
        review: dict[str, Any] = {"pass": True, "issues": []}
        for attempt in range(max_retries + 1):
            stage_result["attempts"] = attempt + 1
            retry_note = ""
            if issues:
                retry_note = "\n\n이전 산출물 문제를 모두 고치세요:\n- " + "\n- ".join(issues)
            text = _call(generate, prompt + retry_note, stage.max_tokens)
            issues = validate_artifact(stage, text)
            if verifier and not issues:
                review = verifier(f"{stage.title}이 사용자 요청과 헌법을 충족하는지 검토", text)
                if review.get("pass") is not True:
                    issues.extend(str(item) for item in review.get("issues", []) if str(item).strip())
                    if not issues:
                        issues.append("같은 모델 검증기를 통과하지 못함")
            if not issues:
                break

        if issues and fallback:
            fallback_prompt = prompt + "\n\n로컬 생성이 다음 검증에 실패했습니다:\n- " + "\n- ".join(issues)
            text = _call(fallback, fallback_prompt, stage.max_tokens)
            issues = validate_artifact(stage, text)
            stage_result["source"] = "expert_api"

        artifact_path = feature_dir / stage.filename
        artifact_path.write_text(text, encoding="utf-8")
        artifacts[stage.name] = text
        stage_result.update({
            "ok": not issues,
            "issues": issues,
            "review": review,
            "path": str(artifact_path),
        })
        manifest["stages"].append(stage_result)

    manifest["ok"] = all(stage["ok"] for stage in manifest["stages"])
    manifest_path = feature_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest
