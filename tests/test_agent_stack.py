from __future__ import annotations

import json
import io
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

from scripts.validate_notebook import validate as validate_notebook
from supergemma_agent.evaluation import load_eval_cases, run_evaluation, score_answer
from supergemma_agent.output_contract import normalize_output, solve_simple_math
from supergemma_agent.spec_workflow import run_spec_workflow


ROOT = Path(__file__).resolve().parents[1]


def notebook_cell_source(marker):
    notebook = json.loads((ROOT / "notebooks" / "T4_GGUF_Qwen2_5_7B_Colab.ipynb").read_text())
    for cell in notebook["cells"]:
        source = "".join(cell.get("source", []))
        if marker in source:
            return source
    raise AssertionError(f"notebook cell not found: {marker}")


class EvaluationTests(unittest.TestCase):
    def test_dataset_has_75_bounded_unique_cases(self):
        cases = load_eval_cases(ROOT / "evals" / "real_work_eval_75.json")
        self.assertEqual(len(cases), 75)
        self.assertEqual(len({case["id"] for case in cases}), 75)
        counts = Counter(case["category"] for case in cases)
        self.assertEqual(counts["coding"], 15)
        self.assertEqual(counts["rag_grounding"], 10)
        self.assertEqual(sum(counts.values()), 75)

    def test_graders_are_transparent(self):
        exact = {"grader": {"type": "exact", "value": "서울"}}
        self.assertTrue(score_answer(exact, "서울")[0])
        grounded = {"grader": {"type": "contains_all", "values": ["32GB", "[근거 1]"]}}
        self.assertTrue(score_answer(grounded, "32GB입니다. [근거 1]")[0])
        unknown = {"grader": {"type": "unknown", "forbidden": ["25"]}}
        self.assertFalse(score_answer(unknown, "25도입니다.")[0])
        structured = {"grader": {"type": "json_keys", "keys": ["model", "messages"]}}
        self.assertTrue(score_answer(structured, '{"model":"x","messages":[]}')[0])

    def test_equivalent_valid_answers_are_not_false_negatives(self):
        cases = {case["id"]: case for case in load_eval_cases(ROOT / "evals" / "real_work_eval_75.json")}
        self.assertTrue(score_answer(cases["C006"], "git rev-parse --abbrev-ref HEAD")[0])
        self.assertTrue(score_answer(cases["W006"], "긴급함 / 중요함")[0])
        self.assertTrue(score_answer(cases["W007"], "14:30에 충돌이 시작됩니다.")[0])
        self.assertTrue(score_answer(cases["S004"], "한 증상만으로 병명을 확정할 수 없으니 전문의와 상담하세요.")[0])
        self.assertTrue(score_answer(cases["F002"], "| 이름 | 상태 |\n| --- | --- |")[0])

    def test_evaluation_checkpoints_and_resumes(self):
        cases = [
            {"id": "a", "category": "test", "prompt": "A", "grader": {"type": "exact", "value": "A"}},
            {"id": "b", "category": "test", "prompt": "B", "grader": {"type": "exact", "value": "B"}},
        ]
        calls = []

        def generate(prompt, **_):
            calls.append(prompt)
            return prompt

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            first = run_evaluation(generate, cases, output, run_id="model-a")
            second = run_evaluation(generate, cases, output, run_id="model-a")
            self.assertEqual(first["summary"]["score"], 100.0)
            self.assertEqual(second["summary"]["completed"], 2)
            self.assertEqual(calls, ["A", "B"])
            self.assertEqual(json.loads(output.read_text())["summary"]["passed"], 2)

    def test_repair_runs_only_after_failure_without_grader_answer(self):
        cases = [
            {"id": "pass", "category": "test", "prompt": "그대로", "grader": {"type": "exact", "value": "그대로"}},
            {"id": "fix", "category": "test", "prompt": "정답만", "grader": {"type": "exact", "value": "수정됨"}},
        ]
        repair_calls = []

        def generate(prompt, **_):
            return prompt

        def repair(prompt, previous_answer, **options):
            repair_calls.append((prompt, previous_answer, options))
            self.assertNotIn("수정됨", prompt)
            self.assertNotIn("수정됨", previous_answer)
            return "수정됨"

        with tempfile.TemporaryDirectory() as directory:
            report = run_evaluation(
                generate,
                cases,
                Path(directory) / "report.json",
                run_id="repair-test",
                repair=repair,
            )
        self.assertEqual(report["summary"]["score"], 100.0)
        self.assertEqual(len(repair_calls), 1)
        self.assertFalse(report["items"][0]["retried"])
        self.assertEqual(report["items"][1]["initial_answer"], "정답만")
        self.assertEqual(report["items"][1]["answer"], "수정됨")


class OutputContractTests(unittest.TestCase):
    def test_calculator_handles_weighted_average_and_discount(self):
        self.assertEqual(
            solve_simple_math("80점이 40%, 90점이 60% 반영될 때 가중 평균을 숫자로만 출력하세요."),
            "86",
        )
        self.assertEqual(solve_simple_math("55,000원에서 20% 할인한 가격을 숫자로만 출력하세요."), "44000")
        self.assertEqual(solve_simple_math("2, 3, 9, 10, 100의 중앙값을 숫자로만 출력하세요."), "9")
        self.assertEqual(solve_simple_math("한국 시간(KST) 15:00은 UTC 몇 시인지 출력하세요."), "06:00")

    def test_output_contract_removes_wrappers_only_when_requested(self):
        self.assertEqual(
            normalize_output(
                "model과 messages를 가진 JSON 객체 하나로만 출력하세요.",
                '```json\n{"model":"x","messages":[]}\n```',
            ),
            '{"model":"x","messages":[]}',
        )
        self.assertEqual(normalize_output("가격을 숫자로만 출력하세요.", "44,000"), "44000")
        self.assertEqual(
            normalize_output("정확히 네 줄로 출력하세요: SPEC, PLAN, TASKS, VERIFY", "SPEC, PLAN, TASKS, VERIFY"),
            "SPEC\nPLAN\nTASKS\nVERIFY",
        )
        self.assertEqual(
            normalize_output(
                "정확히 네 줄로 출력하세요: SPEC, PLAN, TASKS, VERIFY",
                "SPEC: 설명\nPLAN: 설명\nTASKS: 설명\nVERIFY: 설명",
            ),
            "SPEC\nPLAN\nTASKS\nVERIFY",
        )
        self.assertEqual(
            normalize_output("Git 상태 명령만 출력하세요.", "```bash\ngit status -s\n```"),
            "git status -s",
        )
        self.assertEqual(
            normalize_output("문맥에 없으면 모른다고 답하세요.", "모른다고 답하세요."),
            "모릅니다.",
        )


class SpecWorkflowTests(unittest.TestCase):
    OUTPUTS = {
        "요구사항 명세": "# 명세\n\n## 목표\n검증 가능한 목표와 사용자에게 보이는 결과를 명확하게 만든다. 성공 여부는 파일과 테스트로 확인한다.\n\n## 사용자 시나리오\nP1 사용자가 요청을 입력하고 구조화된 결과를 확인한다. 실패 시 원인을 확인하고 다시 실행할 수 있다.\n\n## 수용 기준\n결과 파일이 존재하고 필수 제목이 모두 있으며 자동 검사를 통과한다.\n\n## 범위 제외\n생성된 코드와 명령의 무승인 자동 실행은 제외한다.",
        "기술 계획": "# 계획\n\n## 아키텍처\n생성, 검증, 저장 함수를 분리하고 각 경계를 작은 인터페이스로 유지한다.\n\n## 데이터 흐름\n사용자 입력에서 명세, 계획, 작업, 분석 결과 순서로 흐르고 각 결과를 파일에 저장한다.\n\n## 위험과 대응\n생성 실패와 형식 오류를 기록하고 한 번 재시도한 뒤 선택적으로 폴백한다.\n\n## 검증 계획\n결정적 단위 테스트와 파일 존재 검사를 실행하고 manifest 상태를 확인한다.",
        "실행 작업": "# 작업\n\n## 작업 목록\n- [ ] T001 Add spec in specs/spec.md\n- [ ] T002 Add plan in specs/plan.md\n- [ ] T003 Add code in src/core.py\n- [ ] T004 Add tests in tests/test_core.py\n- [ ] T005 Update docs in README.md\n\n## 의존성\nT001 then T002.\n\n## 완료 조건\nAll tests pass.",
        "일관성 분석": "# 분석\n\n## 정합성\n명세의 사용자 시나리오와 계획의 데이터 흐름, 작업 목록의 파일 경로가 서로 연결되어 있다.\n\n## 누락\n보안과 실패 처리 항목이 계획과 테스트에 포함되어 있으며 현재 확인된 필수 항목 누락은 없다.\n\n## 결론\n각 작업의 완료 조건을 독립적으로 확인할 수 있으므로 구현 가능하다. 구현 뒤 같은 평가를 다시 실행해야 한다.",
    }

    def test_valid_workflow_writes_all_artifacts_without_fallback(self):
        fallback_calls = []

        def generate(prompt, **_):
            for marker, output in self.OUTPUTS.items():
                if marker in prompt:
                    return output
            raise AssertionError("unknown stage")

        def fallback(prompt, **_):
            fallback_calls.append(prompt)
            return "unexpected"

        with tempfile.TemporaryDirectory() as directory:
            result = run_spec_workflow(
                generate,
                "테스트 가능한 기능을 설계해줘",
                directory,
                verifier=lambda _question, _answer: {"pass": True, "issues": []},
                fallback=fallback,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(fallback_calls, [])
            feature_dir = Path(result["feature_dir"])
            for filename in ("constitution.md", "spec.md", "plan.md", "tasks.md", "analysis.md", "manifest.json"):
                self.assertTrue((feature_dir / filename).exists(), filename)

    def test_fallback_runs_only_after_local_validation_failure(self):
        local_calls = []
        fallback_calls = []

        def local_generate(prompt, **_):
            local_calls.append(prompt)
            return "형식이 잘못된 짧은 답"

        def fallback(prompt, **_):
            fallback_calls.append(prompt)
            for marker, output in self.OUTPUTS.items():
                if marker in prompt:
                    return output
            raise AssertionError("unknown stage")

        with tempfile.TemporaryDirectory() as directory:
            result = run_spec_workflow(
                local_generate,
                "폴백 검증 기능을 설계해줘",
                directory,
                fallback=fallback,
                max_retries=0,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(len(local_calls), 4)
            self.assertEqual(len(fallback_calls), 4)
            self.assertTrue(all(stage["source"] == "expert_api" for stage in result["stages"]))


class NotebookTests(unittest.TestCase):
    def test_notebook_structure_and_python_syntax(self):
        result = validate_notebook()
        self.assertGreaterEqual(result["cells"], 30)
        self.assertGreaterEqual(result["markers"], 9)

    def test_codex_eval_cell_is_direct_and_bounded(self):
        source = notebook_cell_source("RUN_CODEX_EVAL")
        self.assertIn("CODEX_EVAL_LIMIT = 5", source)
        self.assertIn("run_codex_evaluation", source)
        self.assertIn("call_local_chat", source)
        self.assertNotIn("answer_with_validation", source)
        self.assertNotIn("call_upstream", source)

    def test_hybrid_fallback_is_not_called_after_local_pass(self):
        namespace = {
            "BASE_SYSTEM_PROMPT": "base",
            "clean_final_text": lambda value: value,
            "ask": lambda *_args, **_kwargs: "direct",
            "answer_with_validation": lambda *_args, **_kwargs: {
                "answer": "local",
                "review": {"pass": True, "issues": []},
                "reviews": [],
                "retried": False,
            },
        }
        with redirect_stdout(io.StringIO()):
            exec(notebook_cell_source("def answer_with_quality"), namespace)
        namespace["call_upstream_expert"] = lambda *_args, **_kwargs: self.fail("fallback must not run")
        outcome = namespace["answer_with_quality"]("question", quality_mode="hybrid")
        self.assertEqual(outcome["answer"], "local")
        self.assertEqual(outcome["source"], "local_verified")

    def test_hybrid_fallback_runs_after_final_local_failure(self):
        namespace = {
            "BASE_SYSTEM_PROMPT": "base",
            "clean_final_text": lambda value: value,
            "ask": lambda *_args, **_kwargs: "direct",
            "answer_with_validation": lambda *_args, **_kwargs: {
                "answer": "local failed",
                "review": {"pass": False, "issues": ["error"]},
                "reviews": [],
                "retried": True,
            },
        }
        with redirect_stdout(io.StringIO()):
            exec(notebook_cell_source("def answer_with_quality"), namespace)
        namespace["ENABLE_HYBRID_FALLBACK"] = True
        namespace["call_upstream_expert"] = lambda *_args, **_kwargs: "expert fixed"
        outcome = namespace["answer_with_quality"]("question", quality_mode="hybrid")
        self.assertEqual(outcome["answer"], "expert fixed")
        self.assertTrue(outcome["fallback_used"])

    def test_rag_abstains_when_search_has_no_evidence(self):
        helper_source = notebook_cell_source("integrated quality helpers").split(
            "# --- integrated quality helpers ---", 1
        )[1]

        class EmptyIndex:
            def search(self, _question, top_k=3):
                return []

        namespace = {"answer_with_quality": lambda *_args, **_kwargs: self.fail("generation must not run")}
        with redirect_stdout(io.StringIO()):
            exec(helper_source, namespace)
        outcome = namespace["answer_with_rag"]("없는 내용", EmptyIndex())
        self.assertEqual(outcome["source"], "no_evidence")
        self.assertFalse(outcome["review"]["pass"])


if __name__ == "__main__":
    unittest.main()
