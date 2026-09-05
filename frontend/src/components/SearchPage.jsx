import { useState } from "react";
import LoadingSpinner, { ResultSkeletonList } from "./LoadingSpinner.jsx";

const API_BASE = "http://localhost:8000";
const SEARCH_RESULT_LIMIT = 15;

const EXAMPLE_QUERIES = [
  "Sudden provocation reducing murder to culpable homicide",
  "Right of private defence exceeding reasonable force",
  "Common intention under Section 34",
];

function deduplicateByCaseName(results) {
  const seen = new Set();
  const deduped = [];

  for (const result of results) {
    const key = result.case_name;
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    deduped.push(result);
  }

  return deduped;
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
          {results.map((result, index) => (
            <li
              key={result.case_name}
              className="search-result search-result-enter"
              style={{ animationDelay: `${index * 75}ms` }}
            >
              <h2>{result.case_name}</h2>
              <p className="search-meta">
                {result.court}
                {result.year ? ` · ${result.year}` : ""}
              </p>
              {result.ipc_sections?.length > 0 && (
                <p className="search-sections">
                  IPC: {result.ipc_sections.join(", ")}
                </p>
              )}
              <p className="search-snippet">{result.snippet}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
