import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bm25_search import bm25_search

results = bm25_search("culpable homicide not amounting to murder", n_results=10)
for r in results:
    print(r["case_name"], "|", r["ipc_sections"], "|", r["snippet"][:80])