# Dense, BM25, and Hybrid Retrieval Findings

## Scope

`evaluate_retrieval_hybrid.py` evaluated MiniLM dense retrieval, BM25 keyword
retrieval, and a reciprocal-rank-fusion (RRF, k=60) hybrid across the same 15
labeled queries in `test_queries.json`. Results were deduplicated to unique
case names in first-occurrence order before calculating precision@5, recall@5,
and reciprocal rank.

## Headline metrics

| Method | Mean precision@5 | Mean recall@5 | MRR |
| --- | ---: | ---: | ---: |
| MiniLM dense | 0.307 | 0.494 | 0.595 |
| BM25 keyword | 0.413 | 0.548 | 0.733 |
| Hybrid RRF | 0.320 | 0.475 | 0.645 |

BM25 alone outperformed both MiniLM dense retrieval and the RRF hybrid on all
three metrics. This is counter to the common assumption that combining keyword
and dense retrieval is necessarily better than either method alone.

## Why keyword retrieval works well here

The legal queries and judgments share highly specific, formal vocabulary:
section numbers and doctrinal phrases such as "dying declaration" and
"circumstantial evidence." Literal keyword matching can therefore retrieve
directly relevant judgments without needing a semantic approximation, giving
BM25 an advantage over the general-purpose dense model on this corpus.

## Why naive RRF did not improve on BM25

RRF rewards cases that are ranked highly by both retrieval methods. That is
useful when the methods have complementary strengths of similar quality, but
here BM25 is consistently stronger. Adding the weaker dense rankings dilutes
BM25's ordering rather than improving it, which is a known limitation of
unweighted rank fusion in information retrieval literature. The resulting
hybrid improved over MiniLM on precision@5 and MRR, but remained behind BM25
on every aggregate metric.

## Corpus data-quality caveat

During the BM25 implementation, a source-data corruption pattern was found in
37 of 48 judgments (77%). The source dataset's anonymization pipeline garbles
some common words, for example converting "not" to "number" and "court" to
"companyrt." This likely limits BM25's ability to exploit negation phrasing
such as "not amounting to murder," even though BM25 still outperformed dense
retrieval overall.

## Recommendation

Treat BM25 as the leading candidate for primary retrieval in this domain.
Alternatively, evaluate weighted fusion that gives BM25 more influence than
dense retrieval. This is a candidate architecture change for future work and
is distinct from the original hypothesis that an unweighted hybrid would
outperform both individual methods.
