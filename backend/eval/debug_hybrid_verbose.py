import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search import search_judgments
from bm25_search import bm25_search

query = "When is culpable homicide punished under IPC Section 304 rather than as murder?"

print("=== DENSE (top 15) ===")
dense_results = search_judgments(query, n_results=15)
seen = set()
rank = 0
for r in dense_results:
    if r["case_name"] in seen:
        continue
    seen.add(r["case_name"])
    rank += 1
    print(rank, r["case_name"], r["ipc_sections"])

print("\n=== BM25 (top 15) ===")
bm25_results = bm25_search(query, n_results=15)
for i, r in enumerate(bm25_results, 1):
    print(i, r["case_name"], r["ipc_sections"])