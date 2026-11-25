# Fair Retrieval Evaluation Findings

## Protocol

- Labeled queries: 15
- Corpus chunks: 533
- Corpus SHA-256: `87cf2647a5dddd5870c84a8039a5a774edca33dc8fc470199a1b356608d67c32`
- Candidates: up to 100 positive-score BM25 chunks or dense chunks with `distance_threshold=None`.
- All rankings are collapsed to unique case names in first-occurrence order before scoring.
- Bootstrap: 1000 paired query resamples, seed 0; percentile 95% CIs.
- Hybrid RRF weights are exploratory because they are compared on these same 15 queries.

## Model names

- MiniLM dense: `all-MiniLM-L6-v2`
- BGE-M3 dense: `BAAI/bge-m3`
- BM25: `rank_bm25.BM25Okapi` over the existing chunk text

## Mean metrics (95% bootstrap CI)

| Method | P@5 | R@5 | MRR | nDCG@5 | Hit@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| MiniLM | 0.307 [0.200, 0.413] | 0.494 [0.299, 0.672] | 0.595 [0.421, 0.774] | 0.502 [0.344, 0.663] | 0.867 [0.667, 1.000] |
| BM25 | 0.413 [0.307, 0.534] | 0.548 [0.396, 0.704] | 0.733 [0.600, 0.867] | 0.623 [0.508, 0.746] | 1.000 [1.000, 1.000] |
| BGE-M3 | 0.373 [0.293, 0.453] | 0.535 [0.378, 0.694] | 0.644 [0.500, 0.789] | 0.565 [0.443, 0.701] | 1.000 [1.000, 1.000] |
| RRF BM25:dense 1:1 | 0.360 [0.253, 0.480] | 0.501 [0.318, 0.677] | 0.620 [0.458, 0.794] | 0.543 [0.397, 0.694] | 0.933 [0.800, 1.000] |
| RRF BM25:dense 2:1 | 0.413 [0.280, 0.547] | 0.532 [0.359, 0.703] | 0.593 [0.443, 0.756] | 0.575 [0.429, 0.725] | 0.933 [0.800, 1.000] |
| RRF BM25:dense 3:1 | 0.387 [0.267, 0.520] | 0.521 [0.342, 0.698] | 0.643 [0.487, 0.806] | 0.573 [0.430, 0.720] | 0.933 [0.800, 1.000] |

## Paired differences vs BM25 (95% bootstrap CI)

Positive values favor the candidate method.

| Method | P@5 | R@5 | MRR | nDCG@5 | Hit@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| MiniLM | -0.107 [-0.213, -0.027] | -0.054 [-0.124, +0.010] | -0.138 [-0.312, +0.036] | -0.121 [-0.249, +0.008] | -0.133 [-0.333, +0.000] |
| BM25 | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| BGE-M3 | -0.040 [-0.120, +0.027] | -0.013 [-0.072, +0.041] | -0.089 [-0.245, +0.056] | -0.058 [-0.168, +0.045] | +0.000 [+0.000, +0.000] |
| RRF BM25:dense 1:1 | -0.053 [-0.120, +0.013] | -0.047 [-0.132, +0.028] | -0.113 [-0.251, +0.027] | -0.080 [-0.162, +0.001] | -0.067 [-0.200, +0.000] |
| RRF BM25:dense 2:1 | -0.000 [-0.053, +0.053] | -0.017 [-0.098, +0.048] | -0.141 [-0.260, -0.044] | -0.048 [-0.111, +0.007] | -0.067 [-0.200, +0.000] |
| RRF BM25:dense 3:1 | -0.027 [-0.080, +0.027] | -0.027 [-0.106, +0.035] | -0.091 [-0.207, +0.000] | -0.050 [-0.113, +0.004] | -0.067 [-0.200, +0.000] |

## Ceiling and skipped methods

- Mean achievable P@5 ceiling from the labels: 0.680.
- No methods were skipped.
