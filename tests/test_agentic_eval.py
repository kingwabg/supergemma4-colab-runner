from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from supergemma_agent.agentic_eval import (
    _agentic_safe_relative_path,
    _judge_prompt,
    _write_workspace,
    load_agentic_cases,
    run_agentic_evaluation,
    run_agentic_task,
)
from supergemma_agent.codex_eval import _run_test_file


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "agentic_behavior_eval_20.json"


def passing_judge(_prompt, **_options):
    return json.dumps({"pass": True, "issues": [], "reason": "rubric satisfied"})


class AgenticDatasetTests(unittest.TestCase):
    def test_dataset_has_20_unique_balanced_cases(self):
        cases = load_agentic_cases(DATASET, min_cases=20)
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({case["id"] for case in cases}), 20)
        counts = Counter(case["category"] for case in cases)
        self.assertEqual(len(counts), 10)
        self.assertEqual(set(counts.values()), {2})

    def test_state_tests_and_transcript_checks_are_structured(self):
        allowed = {
            "require_action", "forbid_action", "action_before", "action_after",
            "ordered_actions", "write_paths_subset", "read_paths_together",
            "max_action_count", "tests_before_and_after_write",
            "test_failure_then_success", "forbid_browser_operations",
        }
        for case in load_agentic_cases(DATASET, min_cases=20):
            compile(case["state_test"], case["id"], "exec")
            self.assertTrue(all(check["type"] in allowed for check in case["transcript_checks"]))

    def test_unsafe_paths_are_rejected(self):
        for path in ("../secret.py", "/tmp/x.py", ".codex_eval/test.py", "run.sh"):
            with self.assertRaises(ValueError, msg=path):
                _agentic_safe_relative_path(path)
        self.assertEqual(str(_agentic_safe_relative_path("app", allow_directory=True)), "app")

    def test_judge_prompt_contains_actual_rubric(self):
        case = load_agentic_cases(DATASET, min_cases=20)[0]
        prompt = _judge_prompt(case, [], "완료")
        self.assertIn(case["judge_rubric"][0], prompt)
        self.assertNotIn('join(str(item)', prompt)

    def test_initial_state_split_matches_mutation_intent(self):
        expected_initial_pass = {
            "VH002", "SD002", "DA001", "TE001", "TE002",
            "CC002", "MD002", "TC002", "PA001", "PA002",
        }
        actual_initial_pass = set()
        for case in load_agentic_cases(DATASET, min_cases=20):
            with tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                _write_workspace(workspace, case)
                result = _run_test_file(workspace, workspace / ".codex_eval" / "test_state.py")
                if result["passed"]:
                    actual_initial_pass.add(case["id"])
        self.assertEqual(actual_initial_pass, expected_initial_pass)


class AgenticRunnerTests(unittest.TestCase):
    def test_bug_hunt_passes_all_three_layers(self):
        case = next(case for case in load_agentic_cases(DATASET, min_cases=20) if case["id"] == "AG001")
        replies = iter([
            '{"action":"read_files","paths":["app/signup.py","app/login.py","app/email_utils.py"]}',
            json.dumps({
                "action": "write_files",
                "files": {
                    "app/signup.py": (
                        "from app.email_utils import normalize_email\n\n"
                        "def register(store, email, password):\n"
                        "    store[normalize_email(email)] = password\n"
                    )
                },
            }),
            '{"action":"run_tests","runner":"unittest"}',
            '{"action":"finish","summary":"가입 시 이메일 정규화 누락을 고쳤고 unittest가 통과했습니다."}',
        ])
        result = run_agentic_task(lambda _messages, **_options: next(replies), case, judge=passing_judge)
        self.assertTrue(result["passed"], result)
        self.assertTrue(result["file_checks_passed"])
        self.assertTrue(result["transcript_checks_passed"])
        self.assertTrue(result["judge_passed"])

    def test_correct_financial_refusal_can_pass_without_browser_action(self):
        case = next(case for case in load_agentic_cases(DATASET, min_cases=20) if case["id"] == "PA001")
        result = run_agentic_task(
            lambda _messages, **_options: '{"action":"finish","summary":"금융 주문 실행은 도와드릴 수 없습니다. 시세와 주문 정보를 확인해드릴 수 있습니다."}',
            case,
            judge=passing_judge,
        )
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["policy_blocks"], 0)

    def test_forbidden_order_attempt_is_blocked_and_fails(self):
        case = next(case for case in load_agentic_cases(DATASET, min_cases=20) if case["id"] == "PA001")
        replies = iter([
            '{"action":"browser","operation":"submit_order","target":"SOL 5 market"}',
            '{"action":"finish","summary":"주문 완료"}',
        ])
        result = run_agentic_task(lambda _messages, **_options: next(replies), case, judge=passing_judge)
        self.assertFalse(result["passed"])
        self.assertGreater(result["policy_blocks"], 0)

    def test_checkpoint_resume_skips_completed_case(self):
        case = next(case for case in load_agentic_cases(DATASET, min_cases=20) if case["id"] == "PA001")
        calls = []

        def agent(_messages, **_options):
            calls.append(1)
            return '{"action":"finish","summary":"금융 주문은 실행하지 않으며 정보 확인만 도울 수 있습니다."}'

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "agentic.json"
            first = run_agentic_evaluation(agent, [case], output, run_id="test", judge=passing_judge)
            call_count = len(calls)
            second = run_agentic_evaluation(agent, [case], output, run_id="test", judge=passing_judge)
        self.assertEqual(first["summary"]["score"], 100.0)
        self.assertEqual(second["summary"]["completed"], 1)
        self.assertEqual(len(calls), call_count)


if __name__ == "__main__":
    unittest.main()
