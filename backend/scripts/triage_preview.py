"""
Prints case_name + a smarter preview of full_text for each judgment,
skipping past the procedural caption boilerplate to show text that
actually describes what happened in the case.

Run from your repo root:
    python backend/scripts/triage_preview.py > triage_output.txt
"""
import json
import re

INPUT_PATH = "backend/data/judgments.jsonl"

# Words that tend to show up in the actual "facts of the case" section,
# not the caption/appearance boilerplate at the top of a judgment.
FACT_INDICATORS = [
    "died", "death", "deceased", "killed", "murder", "assault",
    "attacked", "stabbed", "shot", "beaten", "self defence",
    "self-defence", "private defence", "incident", "occurrence",
]

def find_fact_window(text, window_size=500):
    lowered = text.lower()
    earliest = len(text)
    for word in FACT_INDICATORS:
        idx = lowered.find(word)
        if idx != -1 and idx < earliest:
            earliest = idx
    if earliest == len(text):
        # no fact-indicator found in the whole text — fall back to start
        return text[:window_size]
    start = max(0, earliest - 100)
    return text[start:start + window_size]

with open(INPUT_PATH, encoding="utf-8") as f:
    for i, line in enumerate(f, start=1):
        entry = json.loads(line)
        snippet = find_fact_window(entry["full_text"])
        snippet = re.sub(r"\s+", " ", snippet).strip()
        print(f"\n[{i}] {entry['case_name']} | {entry['court']} | {entry['year']} | sections: {entry['ipc_sections']}")
        print(f"    ...{snippet}...")
