"""corpus/screen_noncandidates.py: flags only documents with in-scope mentions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from corpus import screen_noncandidates as sn  # noqa: E402


def write_text(work_dir: Path, doc_id: str, body: str, headnote: str = "", error: str | None = None) -> None:
    path = work_dir / "text" / f"{doc_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"doc_id": doc_id, "body": body, "headnote": headnote, "error": error,
                                "split_method": "jurisdiction+delivered"}), encoding="utf-8")


def test_screen_flags_lists_and_counts(tmp_path: Path) -> None:
    docs = [{"doc_id": d, "era": "1950-1979", "title": f"T {d}", "case_type": "CRIMINAL APPEAL", "pdf_url": "u"}
            for d in ("murder", "civil", "evidence_only", "no_text", "broken")]
    sample = tmp_path / "noncandidate_sample_criminal_seed1_n5.json"
    sample.write_text(json.dumps({"pool": "criminal", "seed": 1, "documents": docs}), encoding="utf-8")
    write_text(tmp_path, "murder", "Convicted under section 302 Indian Penal Code. The conviction under section 302 stands.")
    write_text(tmp_path, "civil", "Second appeal under section 100 of the Code of Civil Procedure.")
    write_text(tmp_path, "evidence_only", "Indian Penal Code mentioned. Burden under section 106 of the Evidence Act.")
    write_text(tmp_path, "broken", "", error="ValueError: bad pdf")

    lines: list[str] = []
    result = sn.screen(sample, tmp_path, out=lines.append)

    assert result["documents"] == 5 and result["screened"] == 3
    assert result["missing_text"] == ["no_text", "broken"]
    assert [f["doc_id"] for f in result["flagged_documents"]] == ["murder"]
    flagged = result["flagged_documents"][0]
    assert flagged["in_scope_by_rule"] and flagged["included_sections"] == ["302"]
    assert flagged["evidence_body"][0].startswith("[302 explicit] ...")
    assert flagged["human_decision"] is None
    saved = json.loads((tmp_path / "screening" / f"{sample.stem}_flagged.json").read_text(encoding="utf-8"))
    assert saved["flagged"] == 1
    assert not (tmp_path / "pdf").exists()  # never writes to pdf/
    assert any("1 flagged (1 pass the inclusion rule)" in line for line in lines)
