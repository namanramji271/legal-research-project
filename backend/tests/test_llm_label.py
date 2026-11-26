"""corpus/llm_label.py: isolation of the labeller, resumable batches, output checks (fake CLI, no calls)."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import llm_label as L  # noqa: E402
from corpus import validation as v  # noqa: E402

GOOD = {"in_scope": "yes", "section_as_charge": "no", "sections_at_issue": "302", "passing_sections": "",
        "split_correct": "yes", "notes": "", "reason": 'The court upheld the conviction: "the appeal fails".'}


def make_work_dir(tmp_path: Path, n: int = 12) -> tuple[Path, dict]:
    ids = [f"19{50 + i}_{100 + i}" for i in range(n)]
    sample = [{"doc_id": d, "stratum": v.STRATA[i % 5], "primary_sections": ["302"], "loose_sections": ["302"]}
              for i, d in enumerate(ids)]
    key = {"seed": 11, "sample": sample, "calibration": [], "human_subset": ids[:5]}
    (tmp_path / "validation").mkdir()
    (tmp_path / "validation" / "validation_key.json").write_text(json.dumps(key), encoding="utf-8")
    (tmp_path / "text").mkdir()
    for d in ids:
        record = {"doc_id": d, "headnote": f"HEADNOTE-OF-{d[::-1]}",
                  "body": f"KHANNA, J. Body text {d[::-1]} costs $5 per page. " + "x" * 700}
        (tmp_path / "text" / f"{d}.json").write_text(json.dumps(record), encoding="utf-8")
    (tmp_path / "candidates.jsonl").write_text(
        "\n".join(json.dumps({"doc_id": d, "year": 1950 + i, "title": f"State v. Accused {i}", "citation": f"AIR 19{50 + i} SC {i}",
                              "pdf_url": f"https://example.org/{i}.pdf"}) for i, d in enumerate(ids)),
        encoding="utf-8")
    return tmp_path, key


class FakeCLI:
    """Stands in for subprocess.run(claude ...); records every call."""

    def __init__(self, outputs: list[dict] | None = None):
        self.outputs = list(outputs or [])
        self.calls: list[dict] = []

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        if args[1:] == ["--version"]:
            return subprocess.CompletedProcess(args, 0, stdout="9.9.9 (Claude Code)\n", stderr="")
        self.calls.append({"args": args, "input": kwargs["input"], "cwd": kwargs["cwd"],
                           "cwd_listing": os.listdir(kwargs["cwd"])})
        labels = self.outputs.pop(0) if self.outputs else GOOD
        result = {"type": "result", "is_error": False, "structured_output": labels, "total_cost_usd": 0.01,
                  "usage": {"input_tokens": 5, "cache_creation_input_tokens": 900, "output_tokens": 300},
                  "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 5}}}
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(result), stderr="")


def quiet(_: str) -> None:
    pass


def test_prompt_contains_only_this_document_and_the_guideline(tmp_path: Path) -> None:
    work, key = make_work_dir(tmp_path)
    fake = FakeCLI()
    L.run(work, batch_size=3, max_batches=1, runner=fake, executable="claude", out=quiet)
    assert len(fake.calls) == 3
    all_ids = [i["doc_id"] for i in key["sample"]]
    for call in fake.calls:
        prompt = call["input"]
        assert not any(d in prompt for d in all_ids)  # no doc_id, own or other
        # No key or detector fields (the guideline itself mentions the word "stratum", so test the keys).
        assert not any(f in prompt for f in ('"stratum"', "primary_sections", "loose_sections", "human_subset",
                                              "private_defence_range_mention", "explicit_in_body"))
        assert "Annotation guideline: corpus v2" in prompt  # the guideline itself is included
        assert "SHA-256 of this" not in prompt  # maintainer comment stripped
        assert "costs $5 per page" in prompt  # document text is not treated as a template
        # Exactly one document: one headnote marker.
        assert prompt.count("HEADNOTE-OF-") == 1
    # Each call: its own document only, other documents absent.
    first, second = fake.calls[0]["input"], fake.calls[1]["input"]
    head_first = first.split("HEADNOTE-OF-")[1].split()[0]
    assert head_first not in second


def test_each_call_is_a_fresh_toolless_session_in_an_empty_dir(tmp_path: Path) -> None:
    work, _ = make_work_dir(tmp_path)
    fake = FakeCLI()
    L.run(work, batch_size=2, max_batches=1, runner=fake, executable="claude", out=quiet)
    for call in fake.calls:
        args = call["args"]
        assert args[:2] == ["claude", "-p"]
        assert args[args.index("--tools") + 1] == ""
        assert args[args.index("--setting-sources") + 1] == ""
        assert "--strict-mcp-config" in args and "--no-session-persistence" in args
        assert args[args.index("--model") + 1] == "claude-sonnet-5-5"
        assert "--add-dir" not in args and "--continue" not in args and "--resume" not in args
        assert call["cwd_listing"] == [] and Path(call["cwd"]).resolve() != work.resolve()
        assert not Path(call["cwd"]).exists()  # temporary directory removed afterwards
    assert fake.calls[0]["cwd"] != fake.calls[1]["cwd"]


def test_resumable_batches_and_final_outputs(tmp_path: Path) -> None:
    work, key = make_work_dir(tmp_path)
    target = work / "validation"
    fake = FakeCLI()
    first = L.run(work, batch_size=5, max_batches=1, runner=fake, executable="claude", out=quiet)
    assert first == {"done": 5, "total": 12} and len(L.load_state(target / L.STATE_FILE)) == 5
    assert not (target / L.LLM_SHEET).exists()
    L.run(work, batch_size=5, max_batches=1, runner=fake, executable="claude", out=quiet)
    assert len(fake.calls) == 10  # nothing labelled twice
    done = L.run(work, batch_size=5, runner=fake, executable="claude", out=quiet)
    assert done == {"done": 12, "total": 12} and len(fake.calls) == 12
    state_ids = [r["doc_id"] for r in L.load_state(target / L.STATE_FILE)]
    assert state_ids == L.labelling_order(key) and len(set(state_ids)) == 12

    rows = list(csv.DictReader((target / L.LLM_SHEET).open(encoding="utf-8")))
    public = list(csv.DictReader((target / L.PUBLIC_SHEET).open(encoding="utf-8")))
    assert len(rows) == 12 and tuple(rows[0]) == L.LLM_COLUMNS and rows[0]["reason"] == GOOD["reason"]
    assert tuple(public[0]) == v.SHEET_COLUMNS and "reason" not in public[0]
    assert all(r["body_starts_with"] == "" for r in rows + public)  # no judgment text in the sheets
    assert rows[0]["title"].startswith("State v. Accused")
    labels = v.read_labels(target / L.LLM_SHEET)  # scoring can read it
    assert set(labels) == set(state_ids) and labels[state_ids[0]]["in_scope"] == "yes"

    run = json.loads((target / L.RUN_FILE).read_text(encoding="utf-8"))
    assert run["models"] == ["claude-sonnet-5-5"] and run["requested_model"] == "claude-sonnet-5-5"
    assert run["prompt_sha256"] == L.sha256(L.PROMPT_PATH) and run["guideline_sha256"] == L.sha256(L.GUIDELINE_PATH)
    assert run["cli_version"] == "9.9.9 (Claude Code)" and len(run["dates"]) == 1 and run["documents"] == 12


def test_invalid_output_is_retried_once_then_stops_with_state_kept(tmp_path: Path) -> None:
    work, _ = make_work_dir(tmp_path)
    target = work / "validation"
    both_yes = {**GOOD, "section_as_charge": "yes"}
    # First document: bad then good (retried). Second: bad twice (stop).
    fake = FakeCLI([both_yes, GOOD, {**GOOD, "in_scope": "maybe"}, both_yes])
    with pytest.raises(L.LabelError, match="2 failed attempts on item 2 of 12"):
        L.run(work, batch_size=10, runner=fake, executable="claude", out=quiet)
    assert len(L.load_state(target / L.STATE_FILE)) == 1


def test_changed_prompt_or_guideline_refuses_to_resume(tmp_path: Path) -> None:
    work, key = make_work_dir(tmp_path)
    state = work / "validation" / L.STATE_FILE
    state.write_text(json.dumps({"doc_id": key["sample"][0]["doc_id"], "labels": GOOD, "models": ["m"],
                                 "prompt_sha256": "0" * 64, "guideline_sha256": L.sha256(L.GUIDELINE_PATH),
                                 "date": "2026-11-26", "input_tokens": 1, "output_tokens": 1}) + "\n",
                     encoding="utf-8")
    with pytest.raises(L.LabelError, match="changed since labelling started"):
        L.run(work, runner=FakeCLI(), executable="claude", out=quiet)


def test_dry_run_makes_no_calls(tmp_path: Path) -> None:
    work, _ = make_work_dir(tmp_path)
    fake = FakeCLI()
    lines: list[str] = []
    estimate = L.run(work, dry_run=True, runner=fake, executable="claude", out=lines.append)
    assert fake.calls == [] and estimate["documents"] == 12 and estimate["input_tokens"] > 12 * L.CALL_OVERHEAD_TOKENS
    assert L.run(work, dry_run=True, max_batches=1, runner=fake, out=quiet)["documents"] == 10
    assert not (work / "validation" / L.STATE_FILE).exists()
    assert "No calls made" in lines[-1] and not any("19" in line.split("Documents:")[0] for line in lines)


def test_validate_and_parse_labels() -> None:
    out = L.validate_labels({**GOOD, "In_scope": "x", "in_scope": "YES", "sections_at_issue": "s. 302, 304 Part I",
                             "passing_sections": "300"})
    assert out["in_scope"] == "yes" and out["sections_at_issue"] == "302;304"
    with pytest.raises(L.LabelError, match="reason is empty"):
        L.validate_labels({**GOOD, "reason": " "})
    with pytest.raises(L.LabelError, match="misses"):
        L.validate_labels({"in_scope": "yes"})
    fenced = {"result": "```json\n" + json.dumps(GOOD) + "\n```"}
    assert L._parse_labels(fenced) == GOOD
    with pytest.raises(L.LabelError, match="not JSON"):
        L._parse_labels({"result": "I think it is in scope."})
