import { useEffect, useState } from "react";
import LoadingSpinner from "../components/LoadingSpinner.jsx";
import { API_BASE, authFetch } from "../api";

export default function CounterArgumentsPage({ caseNames, onBack }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [results, setResults] = useState([]);

  useEffect(() => {
    let cancelled = false;

    async function fetchCounterArguments() {
      setLoading(true);
      setError("");
      setResults([]);

      try {
        const response = await authFetch(`${API_BASE}/documents/counter-arguments`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ case_names: caseNames }),
        });

        if (!response.ok) {
          const body = await response.json().catch(() => null);
          const detail = body?.detail;
          throw new Error(
            typeof detail === "string"
              ? detail
              : `Failed to find counter-arguments (${response.status})`,
          );
        }

        const data = await response.json();
        if (!cancelled) {
          setResults(Array.isArray(data.results) ? data.results : []);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message || "Something went wrong.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchCounterArguments();
    return () => {
      cancelled = true;
    };
  }, [caseNames]);

  return (
    <section className="lookup-page counter-arguments-page">
      <div className="comparison-top-bar">
        <button
          type="button"
          className="comparison-back-button"
          onClick={onBack}
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            aria-hidden="true"
            className="comparison-back-icon"
          >
            <path d="M15 6l-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Back to search
        </button>

        <h1 className="comparison-title">
          Counter-Arguments
          <span className="comparison-count-badge">
            {caseNames.length} {caseNames.length === 1 ? "case" : "cases"}
          </span>
        </h1>
      </div>

      <p className="lookup-lead comparison-lead">
        Surface opposing precedents to stress-test supporting cases before relying on them.
      </p>

      {loading && (
        <LoadingSpinner label="Finding opposing precedents and counter-arguments…" />
      )}

      {error && (
        <div className="comparison-error-state">
          <p className="lookup-message lookup-error">{error}</p>
          <button
            type="button"
            className="lookup-button lookup-button-outline lookup-button-sm"
            onClick={onBack}
          >
            Back to search
          </button>
        </div>
      )}

      {!loading && !error && results.length > 0 && (
        <div className="counter-sections-list">
          {results.map((item, index) => (
            <section
              key={item.case_name || index}
              className="counter-case-group search-result-enter"
              style={{ animationDelay: `${index * 80}ms` }}
            >
              <div className="counter-case-header">
                <h2 className="counter-case-title">
                  Counter-arguments for: <span>{item.case_name}</span>
                </h2>
                {item.counter_query && (
                  <p className="counter-query-meta">
                    Searched: <span className="counter-query-text">{item.counter_query}</span>
                  </p>
                )}
              </div>

              {item.counter_cases && item.counter_cases.length > 0 ? (
                <ul className="search-results counter-results-list">
                  {item.counter_cases.map((cc) => (
                    <li key={cc.case_name} className="search-result">
                      <div className="search-result-header">
                        <div className="search-result-heading-group">
                          <h2>{cc.case_name}</h2>
                        </div>
                      </div>
                      <p className="search-meta">
                        {cc.court}
                        {cc.year ? ` · ${cc.year}` : ""}
                      </p>
                      {cc.ipc_sections?.length > 0 && (
                        <p className="search-sections">
                          IPC: {cc.ipc_sections.join(", ")}
                        </p>
                      )}
                      {cc.snippet && (
                        <p className="search-snippet">{cc.snippet}</p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="lookup-message counter-empty-message">
                  No clearly opposing precedent found in the current corpus for this case.
                </p>
              )}
            </section>
          ))}
        </div>
      )}
    </section>
  );
}
