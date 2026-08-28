import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search import search_judgments
from bm25_search import bm25_search
from hybrid_search import hybrid_search

query = "What mental element is required to establish culpable homicide?"
expected = {"ILDC case 1964_288", "ILDC case 1978_213"}

print("=== DENSE top 10 ===")
for i, r in enumerate(search_judgments(query, n_results=15), 1):
    print(i, r["case_name"], "RELEVANT" if r["case_name"] in expected else "")

print("\n=== BM25 top 10 ===")
for i, r in enumerate(bm25_search(query, n_results=15), 1):
    print(i, r["case_name"], "RELEVANT" if r["case_name"] in expected else "")

print("\n=== HYBRID top 10 ===")
for i, r in enumerate(hybrid_search(query, n_results=10), 1):
    print(i, r["case_name"], "RELEVANT" if r["case_name"] in expected else "")