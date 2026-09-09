import { useEffect, useState } from "react";
import LoadingSpinner from "../components/LoadingSpinner.jsx";
import { API_BASE, authFetch } from "../api";

/**
 * Re-uses DocumentUploadPage's SummaryBody logic for rendering
 * **Label:** section headers from the Gemini-formatted summary text.
 */
function SummaryBody({ text }) {
  const parts = text.split(/(\*\*[^*]+:\*\*)/);
  const blocks = [];
  let i = 0;

  while (i < parts.length) {
    const part = parts[i];
    const headerMatch = part.match(/^\*\*(.+):\*\*$/);
    if (headerMatch) {
      const label = headerMatch[1];
      const body = parts[i + 1] ?? "";
      blocks.push({ label, body: body.trim() });
      i += 2;
    } else {
      const trimmed = part.trim();
      if (trimmed) {
        blocks.push({ label: null, body: trimmed });
      }
      i += 1;
    }
  }

  if (blocks.length === 0) {
    return <p className="summary-body-text">{text}</p>;
  }

  return (
    <div className="summary-body">
      {blocks.map((block, idx) =>
        block.label ? (
          <div key={idx} className="summary-section">
            <span className="summary-section-label">{block.label}:</span>
            <span className="summary-section-body">{block.body}</span>
          </div>
        ) : (
          <p key={idx} className="summary-body-text">
            {block.body}
          </p>
        ),
      )}
    </div>
  );
}

export default function ComparisonPage({ caseNames, onBack }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [results, setResults] = useState([]);

  useEffect(() => {
    let cancelled = false;

    async function fetchComparison() {
      setLoading(true);
      setError("");
      setResults([]);

      try {
        const response = await authFetch(`${API_BASE}/judgments/compare`, {
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
              : `Comparison failed (${response.status})`,
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

    fetchComparison();
    return () => {
      cancelled = true;
    };
  }, [caseNames]);

  return (
    <section className="lookup-page comparison-page">
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
          Case comparison
          <span className="comparison-count-badge">
            {caseNames.length} cases
          </span>
        </h1>
      </div>

      <p className="lookup-lead comparison-lead">
        Side-by-side summary of facts, legal questions, holdings, and reasoning
        for each selected judgment.
      </p>

      {loading && (
        <LoadingSpinner label="Generating comparison summaries…" />
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
        <div
          className="comparison-grid"
          style={{ "--col-count": results.length }}
        >
          {results.map((item, index) => (
            <article
              key={item.case_name}
              className="comparison-column search-result-enter"
              style={{ animationDelay: `${index * 80}ms` }}
            >
              {/* Column header */}
              <header className="comparison-column-header">
                <h2 className="comparison-case-name">{item.case_name}</h2>
                <p className="search-meta">
                  {item.court}
                  {item.year ? ` · ${item.year}` : ""}
                </p>
                {item.ipc_sections?.length > 0 && (
                  <div className="comparison-section-tags">
                    {item.ipc_sections.map((sec) => (
                      <span key={sec} className="comparison-section-tag">
                        IPC {sec}
                      </span>
                    ))}
                  </div>
                )}
              </header>

              {/* Summary body */}
              <div className="comparison-summary-body">
                {item.summary ? (
                  <SummaryBody text={item.summary} />
                ) : (
                  <p className="summary-body-text comparison-no-summary">
                    No summary available.
                  </p>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
