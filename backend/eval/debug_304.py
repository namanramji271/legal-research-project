import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search import search_judgments

results = search_judgments(
    "When is culpable homicide punished under IPC Section 304 rather than as murder?",
    n_results=10
)
for r in results:
    print(r["case_name"], "|", r["ipc_sections"], "|", r["snippet"][:100])