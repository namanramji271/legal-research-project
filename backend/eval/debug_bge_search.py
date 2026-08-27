import sys
sys.path.insert(0, "backend")
from search import search_judgments_bge

results = search_judgments_bge("murder during self defence", n_results=5)
for r in results:
    print(r["case_name"], "|", r["ipc_sections"], "|", r["snippet"][:80])