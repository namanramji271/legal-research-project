import { useState } from "react";
import LoadingSpinner, { ResultSkeletonList } from "./LoadingSpinner.jsx";

const API_BASE = "http://localhost:8000";
const SEARCH_RESULT_LIMIT = 15;

const EXAMPLE_QUERIES = [
  "Sudden provocation reducing murder to culpable homicide",
  "Right of private defence exceeding reasonable force",
  "Common intention under Section 34",
];

const RELEVANCE_STRENGTH = {
  "Strong match": 3,
  "Moderate match": 2,
  "Weak match": 1,
};

function deduplicateByCaseName(results) {
  const seen = new Map();
  const deduped = [];

  for (const result of results) {
    const key = result.case_name;
    if (!key) continue;

    if (!seen.has(key)) {
      seen.set(key, deduped.length);
      deduped.push({ ...result });
    } else {
      const idx = seen.get(key);
      const existingStrength =
        RELEVANCE_STRENGTH[deduped[idx].relevance_label] ?? 0;
      const incomingStrength =
        RELEVANCE_STRENGTH[result.relevance_label] ?? 0;
      if (incomingStrength > existingStrength) {
        deduped[idx] = { ...result };
      }
    }
  }

  return deduped;
}

function getMethodBadgeText(methods) {
  if (!Array.isArray(methods) || methods.length === 0) {
    return null;
  }
  const hasDense = methods.includes("dense");
  const hasBm25 = methods.includes("bm25");
  if (hasDense && hasBm25) {
    return "Matched by keyword + semantic search";
  }
  if (hasBm25) {
    return "Matched by keyword search";
  }
  if (hasDense) {
    return "Matched by semantic search";
  }
  return null;
}

function HighlightedSnippet({ text, terms }) {
  if (!text) return null;
  if (!terms || !Array.isArray(terms) || terms.length === 0) {
    return <p className="search-snippet">{text}</p>;
  }

  const validTerms = terms.filter(Boolean);
  if (validTerms.length === 0) {
    return <p className="search-snippet">{text}</p>;
  }

  const escaped = [...validTerms]
    .sort((a, b) => b.length - a.length)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));

  const regex = new RegExp(`(${escaped.join("|")})`, "gi");
  const parts = text.split(regex);

  return (
    <p className="search-snippet">
      {parts.map((part, index) => {
        if (!part) return null;
        const isMatch = validTerms.some(
          (t) => t.toLowerCase() === part.toLowerCase()
        );
        return isMatch ? (
          <mark key={index} className="term-highlight">
            {part}
          </mark>
        ) : (
          part
        );
      })}
    </p>
  );
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [results, setResults] = useState([]);
  const [hasSearched, setHasSearched] = useState(false);

  async function executeSearch(searchQuery) {
    const trimmed = searchQuery.trim();
    if (!trimmed) {
      setError("Enter a search query.");
      setResults([]);
      setHasSearched(false);
      return;
    }

    setLoading(true);
    setError("");
    setResults([]);

    const params = new URLSearchParams({
      q: trimmed,
      n_results: String(SEARCH_RESULT_LIMIT),
    });

    try {
      const response = await fetch(`${API_BASE}/search?${params}`);
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `Search failed (${response.status})`);
      }
      const data = await response.json();
      setResults(deduplicateByCaseName(Array.isArray(data) ? data : []));
      setHasSearched(true);
    } catch (err) {
      setError(err.message || "Something went wrong.");
      setHasSearched(false);
    } finally {
      setLoading(false);
    }
  }

  function handleSearch(event) {
    event.preventDefault();
    executeSearch(query);
  }

  function handleChipClick(exampleQuery) {
    setQuery(exampleQuery);
    executeSearch(exampleQuery);
  }

  return (
    <section className="lookup-page">
      <h1>Judgment search</h1>
      <p className="lookup-lead">
        Search murder, culpable homicide, and private-defence judgments by
        natural language.
      </p>

      <p className="corpus-scope-note">
        Corpus scope: Murder &amp; Culpable Homicide (IPC 299–304) · Private Defence (IPC 96–106)
      </p>

      <form className="lookup-form" onSubmit={handleSearch}>
        <div className="form-card lookup-controls">
          <label className="lookup-field lookup-field-grow">
            <span className="lookup-label">Query</span>
            <input
              className="lookup-input"
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="e.g. sudden provocation reducing murder to culpable homicide"
            />
          </label>

          <button className="lookup-button" type="submit" disabled={loading}>
            {loading ? (
              <>
                <span className="button-spinner" aria-hidden="true" />
                Searching…
              </>
            ) : (
              "Search"
            )}
          </button>
        </div>

        {!loading && results.length === 0 && (
          <div className="query-chips-group">
            <span className="query-chips-label">Suggested queries</span>
            <div className="query-chips">
              {EXAMPLE_QUERIES.map((example) => (
                <button
                  key={example}
                  type="button"
                  className="query-chip"
                  onClick={() => handleChipClick(example)}
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}
      </form>

      {loading && (
        <>
          <LoadingSpinner label="Searching judgment corpus…" />
          <ResultSkeletonList count={3} />
        </>
      )}

      {error && <p className="lookup-message lookup-error">{error}</p>}

      {!loading && !error && hasSearched && results.length === 0 && (
        <p className="lookup-message">No matching judgments found.</p>
      )}

      {!loading && results.length > 0 && (
        <ul className="search-results">
          {results.map((result, index) => {
            const methodBadge = getMethodBadgeText(result.matched_methods);
            const relevanceClass =
              result.relevance_label === "Strong match"
                ? "relevance-badge-strong"
                : result.relevance_label === "Moderate match"
                ? "relevance-badge-moderate"
                : "relevance-badge-weak";

            return (
              <li
                key={result.case_name}
                className="search-result search-result-enter"
                style={{ animationDelay: `${index * 75}ms` }}
              >
                <div className="search-result-header">
                  <h2>{result.case_name}</h2>
                  <div className="match-badges">
                    {result.relevance_label && (
                      <span className={`relevance-badge ${relevanceClass}`}>
                        {result.relevance_label}
                      </span>
                    )}
                    {methodBadge && (
                      <span className="method-badge">{methodBadge}</span>
                    )}
                  </div>
                </div>
                <p className="search-meta">
                  {result.court}
                  {result.year ? ` · ${result.year}` : ""}
                </p>
                {result.ipc_sections?.length > 0 && (
                  <p className="search-sections">
                    IPC: {result.ipc_sections.join(", ")}
                  </p>
                )}
                <HighlightedSnippet
                  text={result.snippet}
                  terms={result.matched_terms}
                />
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
