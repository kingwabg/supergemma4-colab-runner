#!/usr/bin/env python3
"""Static checks for the GPU notebook when a CUDA runtime is unavailable."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "T4_GGUF_Qwen2_5_7B_Colab.ipynb"
REQUIRED_MARKERS = (
    "AGENT_TOOLS_AVAILABLE",
    "answer_with_validation",
    "answer_with_quality",
    "answer_with_rag",
    "run_spec_agent",
    "real_work_eval_75.json",
    "agentic_behavior_eval_20.json",
    'quality_mode = str(payload.get("quality_mode", "direct"))',
    '/v1/rag/query',
    '/v1/spec/run',
)
DEFAULT_OFF_FLAGS = (
    "RUN_VERIFIED_QUESTION",
    "RUN_HYBRID_EXPERT",
    "ENABLE_HYBRID_FALLBACK",
    "RUN_CONTINUOUS_CHAT",
    "RUN_RAG",
    "RUN_SPEC_AGENT",
    "RUN_MODEL_EVAL",
    "RUN_AGENTIC_EVAL",
    "RUN_API_SERVER",
    "OPEN_EXTERNAL_TUNNEL",
)


def source_text(cell):
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else str(source)


def python_only(source: str) -> str:
    kept = []
    for line in source.splitlines():
        if re.match(r"^\s*[!%]", line):
            kept.append("pass  # IPython command omitted by static validator")
        else:
            kept.append(line)
    return "\n".join(kept)


def validate(path: Path = NOTEBOOK) -> dict:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    if notebook.get("nbformat") != 4:
        raise AssertionError("nbformat must be 4")
    cells = notebook.get("cells")
    if not isinstance(cells, list) or not cells:
        raise AssertionError("notebook cells are missing")

    ids = [cell.get("id") for cell in cells]
    if any(not cell_id for cell_id in ids) or len(ids) != len(set(ids)):
        raise AssertionError("cell ids must be present and unique")

    combined = "\n".join(source_text(cell) for cell in cells)
    missing = [marker for marker in REQUIRED_MARKERS if marker not in combined]
    if missing:
        raise AssertionError(f"required notebook markers missing: {missing}")
    for flag in DEFAULT_OFF_FLAGS:
        if not re.search(rf"^{re.escape(flag)}\s*=\s*False\s*$", combined, flags=re.MULTILINE):
            raise AssertionError(f"{flag} must default to False")

    code_cells = 0
    for index, cell in enumerate(cells):
        if cell.get("cell_type") != "code":
            continue
        code_cells += 1
        if cell.get("outputs"):
            raise AssertionError(f"cell {index} contains saved outputs")
        try:
            ast.parse(python_only(source_text(cell)), filename=f"cell-{index}")
        except SyntaxError as error:
            raise AssertionError(f"cell {index} syntax error: {error}") from error
    return {"cells": len(cells), "code_cells": code_cells, "markers": len(REQUIRED_MARKERS)}


if __name__ == "__main__":
    print(validate())
