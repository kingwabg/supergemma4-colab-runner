from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from supergemma_agent.codex_eval import (
    _safe_relative_path,
    load_codex_cases,
    run_codex_evaluation,
    run_codex_task,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "codex_like_eval_50.json"


class CodexDatasetTests(unittest.TestCase):
    def test_dataset_has_50_unique_bounded_tasks(self):
        cases = load_codex_cases(DATASET, min_cases=50)
        self.assertEqual(len(cases), 50)
        self.assertEqual(len({case["id"] for case in cases}), 50)
        counts = Counter(case["category"] for case in cases)
        self.assertEqual(counts["bug_fix"], 12)
        self.assertEqual(counts["multi_file_change"], 8)
        self.assertEqual(counts["safety_tool_use"], 2)

    def test_all_embedded_tests_are_valid_python(self):
        for case in load_codex_cases(DATASET, min_cases=50):
            compile(case["public_test"], f"{case['id']}:public", "exec")
            compile(case["hidden_test"], f"{case['id']}:hidden", "exec")

    def test_unsafe_paths_are_rejected(self):
        for path in ("../secret.py", "/tmp/x.py", ".codex_eval/test.py", "app/run.sh"):
            with self.assertRaises(ValueError, msg=path):
                _safe_relative_path(path)


class CodexRunnerTests(unittest.TestCase):
    def test_agent_edits_runs_tests_and_passes_hidden_test(self):
        case = load_codex_cases(DATASET, min_cases=50)[0]
        replies = iter(
            [
                '{"action":"inspect"}',
                json.dumps(
                    {
                        "action": "write_files",
                        "files": {
                            "app/math_utils.py": (
                                "def clamp(value, minimum, maximum):\n"
                                "    if minimum > maximum:\n"
                                "        raise ValueError('invalid range')\n"
                                "    return max(minimum, min(maximum, value))\n"
                            )
                        },
                    }
                ),
                '{"action":"run_tests"}',
                '{"action":"finish","summary":"clamp fixed"}',
            ]
        )

        result = run_codex_task(lambda _messages, **_options: next(replies), case)
        self.assertTrue(result["passed"], result["hidden_output"])
        self.assertTrue(result["public_tests_passed"])
        self.assertEqual(result["changed_files"], ["app/math_utils.py"])

    def test_dangerous_generated_code_is_blocked(self):
        case = load_codex_cases(DATASET, min_cases=50)[0]
        replies = iter(
            [
                '{"action":"write_files","files":{"app/math_utils.py":"import os\\ndef clamp(*args):\\n    return os.system(\'echo unsafe\')\\n"}}',
                '{"action":"finish","summary":"done"}',
            ]
        )
        result = run_codex_task(lambda _messages, **_options: next(replies), case)
        self.assertFalse(result["passed"])
        self.assertGreater(result["policy_blocks"], 0)

    def test_secret_removal_hidden_test_ignores_binary_cache_files(self):
        case = next(
            item for item in load_codex_cases(DATASET, min_cases=50)
            if item["id"] == "SF001"
        )
        replies = iter(
            [
                '{"action":"read_files","paths":["app/config.py"]}',
                '{"action":"write_files","files":{"app/config.py":"API_KEY = \'\'\\n\\ndef load_api_key(value=None):\\n    return value or API_KEY\\n"}}',
                '{"action":"run_tests"}',
                '{"action":"finish","summary":"secret removed"}',
            ]
        )
        result = run_codex_task(lambda _messages, **_options: next(replies), case)
        self.assertTrue(result["passed"], result["hidden_output"])

    def test_checkpoint_resume_skips_completed_tasks(self):
        case = load_codex_cases(DATASET, min_cases=50)[0]
        calls = []

        def agent(_messages, **_options):
            calls.append(1)
            sequence = len(calls) % 4
            if sequence == 1:
                return '{"action":"inspect"}'
            if sequence == 2:
                return '{"action":"write_files","files":{"app/math_utils.py":"def clamp(value, minimum, maximum):\\n    if minimum > maximum: raise ValueError()\\n    return max(minimum, min(maximum, value))\\n"}}'
            if sequence == 3:
                return '{"action":"run_tests"}'
            return '{"action":"finish","summary":"done"}'

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            first = run_codex_evaluation(agent, [case], output, run_id="test")
            call_count = len(calls)
            second = run_codex_evaluation(agent, [case], output, run_id="test")
        self.assertEqual(first["summary"]["score"], 100.0)
        self.assertEqual(second["summary"]["score"], 100.0)
        self.assertEqual(len(calls), call_count)


if __name__ == "__main__":
    unittest.main()
