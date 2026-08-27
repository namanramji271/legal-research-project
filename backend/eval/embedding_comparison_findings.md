# MiniLM vs. BGE-M3 Retrieval Comparison

## Scope

`evaluate_retrieval_comparison.py` compared the existing MiniLM index with
the separate BGE-M3 index on the same 15 labeled queries in
`test_queries.json`. Both systems retrieved 10 candidate chunks per query,
deduplicated results to unique case names while preserving first occurrence,
and were scored using precision@5, recall@5, and reciprocal rank.

## Headline metrics

| Model | Embedding model | Mean precision@5 | Mean recall@5 | MRR |
| --- | --- | ---: | ---: | ---: |
| MiniLM | `all-MiniLM-L6-v2` | 0.307 | 0.494 | 0.595 |
| BGE-M3 | `BAAI/bge-m3` | 0.360 | 0.524 | 0.644 |

On this test set, BGE-M3 improves all three aggregate retrieval metrics over
MiniLM. The improvement is meaningful but should be interpreted alongside the
per-query variation and the substantially higher embedding cost below.

## Standout result: IPC 304 queries

The largest improvement was on the two IPC 304 queries (#14 and #15). MiniLM
scored precision@5 = 0.000 and recall@5 = 0.000 for both queries, as reported
in `findings.md`. BGE-M3 improved each to precision@5 = 0.400 and recall@5 =
0.222.

This supports the hypothesis from `findings.md` that a stronger embedding
model can better handle the comparative and negation phrasing in questions
about culpable homicide "not amounting to murder." That phrasing previously
favoured IPC 302-adjacent results in the MiniLM ranking, despite IPC 304 being
the intended subject.

## Per-query caveat

BGE-M3 is not uniformly better. On queries 6, 11, 12, and 13, BGE-M3
performed equal to or worse than MiniLM. The aggregate improvement is therefore
concentrated in the previously weak IPC 304 queries rather than evidence of a
blanket upgrade across every legal-retrieval topic.

## Build-time trade-off

BGE-M3 took approximately 37–38 minutes (2262.7 seconds) to embed the
533-chunk corpus on CPU without a GPU. MiniLM embedded the same corpus nearly
instantly. This is a real operational cost whenever the corpus changes, the
index is rebuilt, or the system is redeployed.

## Recommendation

Treat BGE-M3 as a valid future-work direction rather than an unconditional
replacement for MiniLM. A hybrid dense-plus-BM25 approach may retain semantic
benefits while recovering exact statutory contrasts. Alternatively, switching
to BGE-M3 is more compelling if corpus expansion specifically strengthens
underrepresented sections such as IPC 304, where this comparison showed the
clearest benefit.
