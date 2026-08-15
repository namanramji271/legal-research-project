import { useState } from "react";

const API_BASE = "http://localhost:8000";
const SEARCH_RESULT_LIMIT = 15;

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

  async function handleSearch(event) {
    event.preventDefault();
    const trimmed = query.trim();
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

  return (
    <section className="lookup-page">
      <h1>Judgment Search</h1>
      <p className="lookup-lead">
        Search murder, culpable homicide, and private-defence judgments by
        natural language.
      </p>

      <form className="lookup-form" onSubmit={handleSearch}>
        <div className="lookup-controls">
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
            {loading ? "Searching…" : "Search"}
          </button>
        </div>
      </form>

      {error && <p className="lookup-message lookup-error">{error}</p>}

      {!loading && !error && hasSearched && results.length === 0 && (
        <p className="lookup-message">No matching judgments found.</p>
      )}

      {results.length > 0 && (
        <ul className="search-results">
          {results.map((result) => (
            <li key={result.case_name} className="search-result">
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
