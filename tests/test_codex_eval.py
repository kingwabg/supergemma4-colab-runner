from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from supergemma_agent.codex_eval import (
    _parse_codex_action,
    _safe_relative_path,
    load_codex_cases,
    run_codex_evaluation,
    run_codex_repeated_evaluation,
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
        self.assertTrue(all(case["max_steps"] == 8 for case in cases))
        self.assertTrue(all(case["require_plan"] is True for case in cases))

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
                '{"action":"plan","checklist":["범위 제한","잘못된 범위는 ValueError"]}',
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
                '{"action":"finish","summary":"clamp fixed","checklist_verified":true}',
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
                '{"action":"plan","checklist":["기존 공개 API 유지","위험 호출 금지"]}',
                '{"action":"write_files","files":{"app/math_utils.py":"import os\\ndef clamp(*args):\\n    return os.system(\'echo unsafe\')\\n"}}',
                '{"action":"finish","summary":"done","checklist_verified":true}',
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
                '{"action":"plan","checklist":["비밀 제거","README 보존"]}',
                '{"action":"read_files","paths":["app/config.py"]}',
                '{"action":"write_files","files":{"app/config.py":"API_KEY = \'\'\\n\\ndef load_api_key(value=None):\\n    return value or API_KEY\\n"}}',
                '{"action":"run_tests"}',
                '{"action":"finish","summary":"secret removed","checklist_verified":true}',
            ]
        )
        result = run_codex_task(lambda _messages, **_options: next(replies), case)
        self.assertTrue(result["passed"], result["hidden_output"])

    def test_checkpoint_resume_skips_completed_tasks(self):
        case = load_codex_cases(DATASET, min_cases=50)[0]
        calls = []

        def agent(_messages, **_options):
            calls.append(1)
            sequence = len(calls) % 5
            if sequence == 1:
                return '{"action":"plan","checklist":["범위 제한","ValueError"]}'
            if sequence == 2:
                return '{"action":"inspect"}'
            if sequence == 3:
                return '{"action":"write_files","files":{"app/math_utils.py":"def clamp(value, minimum, maximum):\\n    if minimum > maximum: raise ValueError()\\n    return max(minimum, min(maximum, value))\\n"}}'
            if sequence == 4:
                return '{"action":"run_tests"}'
            return '{"action":"finish","summary":"done","checklist_verified":true}'

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            first = run_codex_evaluation(agent, [case], output, run_id="test")
            call_count = len(calls)
            second = run_codex_evaluation(agent, [case], output, run_id="test")
        self.assertEqual(first["summary"]["score"], 100.0)
        self.assertEqual(second["summary"]["score"], 100.0)
        self.assertEqual(len(calls), call_count)

    def test_sentinel_write_preserves_regex_without_json_escaping(self):
        raw = r"""<<<WRITE_FILE app/redaction.py>>>
def redact(text):
    pattern = r'(password|token)\s*[=:]\s*\S+'
    return pattern
<<<END_WRITE_FILE>>>"""
        action = _parse_codex_action(raw)
        self.assertEqual(action["format"], "sentinel")
        self.assertIn(r"\s*[=:]\s*\S+", action["files"]["app/redaction.py"])

    def test_auto_submit_is_reported_only_in_system_track(self):
        case = dict(load_codex_cases(DATASET, min_cases=50)[0])
        case["max_steps"] = 3
        replies = iter([
            '{"action":"plan","checklist":["범위 제한","ValueError"]}',
            """<<<WRITE_FILE app/math_utils.py>>>
def clamp(value, minimum, maximum):
    if minimum > maximum:
        raise ValueError()
    return max(minimum, min(maximum, value))
<<<END_WRITE_FILE>>>""",
            '{"action":"run_tests"}',
        ])
        seen_options = []

        def agent(_messages, **options):
            seen_options.append(options)
            return next(replies)

        result = run_codex_task(agent, case)
        self.assertFalse(result["strict_track_passed"])
        self.assertTrue(result["system_track_passed"], result["hidden_output"])
        self.assertTrue(result["auto_submitted"])
        self.assertEqual(seen_options[0]["response_format"], {"type": "json_object"})
        self.assertNotIn("response_format", seen_options[1])

    def test_repeated_evaluation_reports_mean_and_stddev(self):
        case = next(item for item in load_codex_cases(DATASET, min_cases=50) if item["id"] == "BF001")
        calls = 0

        def agent(_messages, **_options):
            nonlocal calls
            sequence = calls % 4
            calls += 1
            if sequence == 0:
                return '{"action":"plan","checklist":["범위 제한","ValueError"]}'
            if sequence == 1:
                return """<<<WRITE_FILE app/math_utils.py>>>
def clamp(value, minimum, maximum):
    if minimum > maximum: raise ValueError()
    return max(minimum, min(maximum, value))
<<<END_WRITE_FILE>>>"""
            if sequence == 2:
                return '{"action":"run_tests"}'
            return '{"action":"finish","summary":"done","checklist_verified":true}'

        with tempfile.TemporaryDirectory() as directory:
            batch = run_codex_repeated_evaluation(
                agent,
                [case],
                Path(directory) / "repeated.json",
                run_id="repeat-test",
                repeats=2,
            )
            self.assertTrue(Path(batch["aggregate_path"]).exists())
        self.assertEqual(batch["aggregate"]["repeats"], 2)
        self.assertEqual(batch["aggregate"]["strict_score_mean"], 100.0)
        self.assertEqual(batch["aggregate"]["strict_score_stddev"], 0.0)

    def test_heldout_summary_mode_does_not_store_transcript_or_outputs(self):
        case = load_codex_cases(DATASET, min_cases=50)[0]
        replies = iter([
            '{"action":"plan","checklist":["범위 제한","ValueError"]}',
            """<<<WRITE_FILE app/math_utils.py>>>
def clamp(value, minimum, maximum):
    if minimum > maximum: raise ValueError()
    return max(minimum, min(maximum, value))
<<<END_WRITE_FILE>>>""",
            '{"action":"run_tests"}',
            '{"action":"finish","summary":"done","checklist_verified":true}',
        ])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "heldout.json"
            report = run_codex_evaluation(
                lambda _messages, **_options: next(replies),
                [case],
                output,
                run_id="heldout-test",
                store_details=False,
            )
            persisted = json.loads(output.read_text())
        self.assertTrue(report["items"][0]["passed"])
        for forbidden in ("transcript", "hidden_output", "public_output", "changed_files", "checklist"):
            self.assertNotIn(forbidden, persisted["items"][0])


if __name__ == "__main__":
    unittest.main()
