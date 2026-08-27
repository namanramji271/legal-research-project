# Retrieval Evaluation Findings

## Scope

`evaluate_retrieval.py` was run against `test_queries.json`, which contains
15 labeled queries covering private defence and IPC Sections 299–304. Each
query retrieved up to 10 judgment chunks and was evaluated at the case level.

## Headline metrics

| Metric | Result |
| --- | ---: |
| Mean precision@5 | 0.307 |
| Mean recall@5 | 0.494 |
| Mean reciprocal rank (MRR) | 0.595 |
| Queries returning zero results | 0 / 15 |

The 0.65 distance threshold did not eliminate every result for any evaluation
query. The main quality issue is therefore ranking and section-level coverage,
not an overly aggressive empty-result threshold for this test set.

## IPC 304 finding

The two IPC 304 queries (#14 and #15) each scored:

| Metric | Result |
| --- | ---: |
| Precision@5 | 0.000 |
| Recall@5 | 0.000 |

Debug output showed that only 2 of the 9 expected relevant cases appeared in
the top 10 results at all. They ranked sixth and seventh, just outside the
top-five cutoff. Most of the top-five slots instead contained judgments tagged
only with IPC 302.

## Proposed explanation

The corpus has a strong section imbalance: IPC 302 is heavily represented
(approximately 40 of 48 judgments), while IPC 304 has comparatively sparse
coverage. This likely biases the dense embedding space toward IPC-302-adjacent
language. The IPC 304 queries also use comparative and negation phrasing, such
as “not amounting to murder.” Dense embedding models often emphasize the topic
words present and can underrepresent the contrast or negation being drawn,
which can further favor murder-related results over the intended IPC 304 cases.

## Implications for planned future work

These findings motivate two planned improvements:

1. Expand corpus coverage for underrepresented sections, particularly IPC 304,
   so retrieval is not dominated by the much larger IPC 302 cluster.
2. Add hybrid search (dense retrieval plus BM25) to preserve semantic matching
   while recovering exact statutory terms and contrasts that dense embeddings
   may miss.
