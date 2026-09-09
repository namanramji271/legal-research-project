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

/**
 * Renders the Sentencing & Evidentiary Patterns panel when is_relevant=true.
 * Highlights themes shared by 2+ of the currently-compared cases.
 */
function ThemeStatsPanel({ stats, caseNames }) {
  const {
    total_labeled_cases,
    untagged_case_count,
    theme_counts,
    selected_case_themes,
  } = stats;

  // Build a set of themes that appear in 2+ of the selected cases
  const sharedThemes = new Set();
  if (selected_case_themes) {
    const themeCaseCount = {};
    for (const caseName of caseNames) {
      const themes = selected_case_themes[caseName] ?? [];
      for (const theme of themes) {
        themeCaseCount[theme] = (themeCaseCount[theme] ?? 0) + 1;
      }
    }
    for (const [theme, count] of Object.entries(themeCaseCount)) {
      if (count >= 2) sharedThemes.add(theme);
    }
  }

  const themeEntries = Object.entries(theme_counts ?? {}).sort(
    ([, a], [, b]) => b - a
  );

  if (themeEntries.length === 0) return null;

  return (
    <section className="theme-stats-panel" aria-label="Sentencing & Evidentiary Patterns">
      <div className="theme-stats-header">
        <h2 className="theme-stats-title">Sentencing &amp; Evidentiary Patterns</h2>
        <p className="theme-stats-subtitle">
          Based on {total_labeled_cases} labeled IPC 302 judgments in the current corpus
        </p>
      </div>

      <ul className="theme-stats-list">
        {themeEntries.map(([theme, count]) => {
          const pct = Math.round((count / total_labeled_cases) * 100);
          const isShared = sharedThemes.has(theme);
          return (
            <li
              key={theme}
              className={`theme-stats-row${isShared ? " theme-stats-row-shared" : ""}`}
            >
              <span className="theme-stats-name">{theme}</span>
              <span className="theme-stats-count">
                {count} of {total_labeled_cases} ({pct}%)
              </span>
              {isShared && (
                <span className="theme-stats-shared-tag" aria-label="Shared by selected cases">
                  Shared
                </span>
              )}
            </li>
          );
        })}
      </ul>

      {untagged_case_count > 0 && (
        <p className="theme-stats-footnote">
          {untagged_case_count} labeled case{untagged_case_count > 1 ? "s" : ""} did not strongly match any theme.
        </p>
      )}
    </section>
  );
}

export default function ComparisonPage({ caseNames, onBack }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [results, setResults] = useState([]);
  const [themeStats, setThemeStats] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchAll() {
      setLoading(true);
      setError("");
      setResults([]);
      setThemeStats(null);

      const body = JSON.stringify({ case_names: caseNames });

      try {
        const [compareRes, themeRes] = await Promise.all([
          authFetch(`${API_BASE}/judgments/compare`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body,
          }),
          authFetch(`${API_BASE}/judgments/theme-stats`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body,
          }),
        ]);

        if (!compareRes.ok) {
          const errBody = await compareRes.json().catch(() => null);
          const detail = errBody?.detail;
          throw new Error(
            typeof detail === "string"
              ? detail
              : `Comparison failed (${compareRes.status})`,
          );
        }

        const data = await compareRes.json();
        if (!cancelled) {
          setResults(Array.isArray(data.results) ? data.results : []);
        }

        // theme-stats is best-effort — don't fail the page if it errors
        if (themeRes.ok) {
          const themeData = await themeRes.json().catch(() => null);
          if (!cancelled && themeData?.is_relevant) {
            setThemeStats(themeData);
          }
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

    fetchAll();
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
        <>
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

          {themeStats && (
            <ThemeStatsPanel stats={themeStats} caseNames={caseNames} />
          )}
        </>
      )}
    </section>
  );
}
