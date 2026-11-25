# Roadmap

- [x] 1. Repo hygiene.
- [x] 2. Fair evaluation: equal-depth case-level retrieval and full chunk text to QA.
  Note: the QA v2 run (`backend/eval/qa_v2_findings.md`) is quota_exhausted with 6 calls remaining; resume with `python backend/eval/evaluate_qa_v2.py`.
- [x] 2b. Make BM25 (with query stopword filtering) the production retriever for /search and /ask (`RETRIEVER`, default bm25).
- [ ] 3. Corpus and IPC-BNS mapping expansion.
- [ ] 4. Wire the mapper into retrieval.
- [ ] 5. Add a reranker, claim-level verifier, and a bigger gold set.
- [ ] 6. Security, tests, and deployment.
- [ ] 7. Rewrite the paper.
