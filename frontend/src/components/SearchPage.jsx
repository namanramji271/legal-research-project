import { useState } from "react";
import LoadingSpinner, { ResultSkeletonList } from "./LoadingSpinner.jsx";
import { authFetch } from "../api";

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

export default function SearchPage({
  auth,
  onCompare,
  onFindCounterArguments,
  query: queryProp,
  setQuery: setQueryProp,
  results: resultsProp,
  setResults: setResultsProp,
  hasSearched: hasSearchedProp,
  setHasSearched: setHasSearchedProp,
}) {
  const [localQuery, setLocalQuery] = useState("");
  const [localResults, setLocalResults] = useState([]);
  const [localHasSearched, setLocalHasSearched] = useState(false);

  const query = queryProp !== undefined ? queryProp : localQuery;
  const setQuery = setQueryProp || setLocalQuery;
  const results = resultsProp !== undefined ? resultsProp : localResults;
  const setResults = setResultsProp || setLocalResults;
  const hasSearched = hasSearchedProp !== undefined ? hasSearchedProp : localHasSearched;
  const setHasSearched = setHasSearchedProp || setLocalHasSearched;

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedCases, setSelectedCases] = useState([]);
  const [caseFileCases, setCaseFileCases] = useState([]);
  const [exporting, setExporting] = useState(false);
  const [clientSummaries, setClientSummaries] = useState({}); // { [case_name]: { loading, error, summary, expanded } }

  const isJudge = auth?.role === "judge";
  const canExport = auth?.role === "lawyer" || auth?.role === "judge";
  const canViewClientSummary = auth?.role === "lawyer" || auth?.role === "judge";
  const MAX_COMPARE = 3;

  async function toggleClientSummary(caseName) {
    const current = clientSummaries[caseName];

    // If already expanded, toggle collapse
    if (current?.expanded) {
      setClientSummaries((prev) => ({
        ...prev,
        [caseName]: { ...prev[caseName], expanded: false },
      }));
      return;
    }

    // If already has summary, re-expand without refetching
    if (current?.summary) {
      setClientSummaries((prev) => ({
        ...prev,
        [caseName]: { ...prev[caseName], expanded: true },
      }));
      return;
    }

    // Fetch from backend
    setClientSummaries((prev) => ({
      ...prev,
      [caseName]: { loading: true, error: "", summary: "", expanded: true },
    }));

    try {
      const res = await authFetch(`${API_BASE}/documents/client-summary`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_name: caseName }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `Failed to fetch client summary (${res.status})`);
      }

      const data = await res.json();
      setClientSummaries((prev) => ({
        ...prev,
        [caseName]: {
          loading: false,
          error: "",
          summary: data.client_summary || "",
          expanded: true,
        },
      }));
    } catch (err) {
      setClientSummaries((prev) => ({
        ...prev,
        [caseName]: {
          loading: false,
          error: err.message || "Failed to load client summary.",
          summary: "",
          expanded: true,
        },
      }));
    }
  }

  function toggleCaseSelection(caseName) {
    setSelectedCases((prev) => {
      if (prev.includes(caseName)) {
        return prev.filter((n) => n !== caseName);
      }
      if (prev.length >= MAX_COMPARE) {
        return prev; // cap at 3
      }
      return [...prev, caseName];
    });
  }

  function toggleCaseFileSelection(caseName) {
    setCaseFileCases((prev) => {
      if (prev.includes(caseName)) {
        return prev.filter((n) => n !== caseName);
      }
      return [...prev, caseName];
    });
  }

  async function handleExportCaseFile() {
    if (caseFileCases.length === 0 || exporting) return;
    setExporting(true);
    setExportError("");

    try {
      const response = await authFetch(`${API_BASE}/documents/export-case-file`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_names: caseFileCases }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        const detail = errorData?.detail || `Export failed (${response.status})`;
        throw new Error(detail);
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "case_file_export.docx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err.message || "Failed to export case file.");
    } finally {
      setExporting(false);
    }
  }

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
      const response = await authFetch(`${API_BASE}/search?${params}`);
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

            const isSelected = selectedCases.includes(result.case_name);
            const isAtCap = selectedCases.length >= MAX_COMPARE && !isSelected;
            const isInCaseFile = caseFileCases.includes(result.case_name);

            return (
              <li
                key={result.case_name}
                className={`search-result search-result-enter${
                  isSelected ? " search-result-selected" : ""
                }${isInCaseFile ? " search-result-in-casefile" : ""}`}
                style={{ animationDelay: `${index * 75}ms` }}
              >
                <div className="search-result-header">
                  <div className="search-result-heading-group">
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

                  {(canExport || isJudge) && (
                    <div className="search-result-actions">
                      {canViewClientSummary && (
                        <button
                          type="button"
                          className={`client-summary-toggle${
                            clientSummaries[result.case_name]?.expanded ? " client-summary-toggle-active" : ""
                          }`}
                          onClick={() => toggleClientSummary(result.case_name)}
                          title={
                            clientSummaries[result.case_name]?.expanded
                              ? "Hide client summary"
                              : "View plain-language summary for clients"
                          }
                          aria-expanded={Boolean(clientSummaries[result.case_name]?.expanded)}
                        >
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                            <path d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                          Client summary
                        </button>
                      )}
                      {canExport && (
                        <button
                          type="button"
                          className={`casefile-toggle${
                            isInCaseFile ? " casefile-toggle-active" : ""
                          }`}
                          onClick={() => toggleCaseFileSelection(result.case_name)}
                          title={
                            isInCaseFile
                              ? "Remove from case file"
                              : "Add to case file"
                          }
                          aria-pressed={isInCaseFile}
                        >
                          {isInCaseFile ? (
                            <>
                              <svg
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="1.5"
                                aria-hidden="true"
                              >
                                <path
                                  d="M5 13l4 4L19 7"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                />
                              </svg>
                              In case file
                            </>
                          ) : (
                            <>
                              <svg
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="1.5"
                                aria-hidden="true"
                              >
                                <path
                                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                />
                              </svg>
                              Add to case file
                            </>
                          )}
                        </button>
                      )}
                      {isJudge && (
                        <button
                          type="button"
                          className={`compare-toggle${isSelected ? " compare-toggle-active" : ""}${isAtCap ? " compare-toggle-disabled" : ""}`}
                          disabled={isAtCap}
                          onClick={() => toggleCaseSelection(result.case_name)}
                          title={
                            isSelected
                              ? "Remove from comparison"
                              : isAtCap
                              ? "Maximum 3 cases selected"
                              : "Add to comparison"
                          }
                          aria-pressed={isSelected}
                        >
                          {isSelected ? (
                            <>
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                                <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                              Added
                            </>
                          ) : (
                            <>
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                                <path d="M12 5v14M5 12h14" strokeLinecap="round" />
                              </svg>
                              Compare
                            </>
                          )}
                        </button>
                      )}
                    </div>
                  )}
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

                {/* Inline accordion for Client summary */}
                {clientSummaries[result.case_name]?.expanded && (
                  <div className="client-summary-panel" role="region" aria-label="Client summary">
                    <div className="client-summary-header">
                      <span className="client-summary-badge">Client summary</span>
                    </div>

                    {clientSummaries[result.case_name]?.loading && (
                      <div className="client-summary-loading">
                        <span className="button-spinner" aria-hidden="true" />
                        Generating plain-language summary…
                      </div>
                    )}

                    {clientSummaries[result.case_name]?.error && (
                      <p className="lookup-message lookup-error client-summary-error">
                        {clientSummaries[result.case_name].error}
                      </p>
                    )}

                    {!clientSummaries[result.case_name]?.loading &&
                      !clientSummaries[result.case_name]?.error &&
                      clientSummaries[result.case_name]?.summary && (
                        <>
                          <p className="client-summary-text">
                            {clientSummaries[result.case_name].summary}
                          </p>
                          <p className="client-summary-caption">
                            Plain-language summary - share with clients as needed.
                          </p>
                        </>
                      )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {/* Fixed bottom action bars — lawyer & judge, always in view together */}
      {((canExport && caseFileCases.length >= 1) || (isJudge && selectedCases.length >= 2)) && (
        <div className="search-action-dock">
          {/* Compare bar sits on top if active */}
          {isJudge && selectedCases.length >= 2 && (
            <div className="compare-action-bar" role="region" aria-label="Case comparison">
              <span className="compare-action-label">
                {selectedCases.length} case{selectedCases.length > 1 ? "s" : ""} selected
              </span>
              <div className="compare-action-buttons">
                <button
                  type="button"
                  className="lookup-button lookup-button-sm"
                  onClick={() => onCompare(selectedCases)}
                >
                  Compare {selectedCases.length} selected
                </button>
                <button
                  type="button"
                  className="lookup-button lookup-button-outline lookup-button-sm"
                  onClick={() => setSelectedCases([])}
                >
                  Clear
                </button>
              </div>
            </div>
          )}

          {/* Case file export bar */}
          {canExport && caseFileCases.length >= 1 && (
            <div
              className="casefile-action-bar"
              role="region"
              aria-label="Case file export"
            >
              <div className="casefile-action-left">
                <span className="casefile-action-label">
                  {caseFileCases.length} case{caseFileCases.length > 1 ? "s" : ""} selected for export
                </span>
                {exportError && (
                  <span className="casefile-export-error">{exportError}</span>
                )}
              </div>
              <div className="casefile-action-buttons">
                <button
                  type="button"
                  className="lookup-button lookup-button-outline lookup-button-sm casefile-counter-button"
                  disabled={exporting}
                  onClick={() => onFindCounterArguments && onFindCounterArguments(caseFileCases)}
                  title="Find opposing precedents for selected cases"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                    <path d="M7 16V4m0 0L3 8m4-4l4 4m6 4v12m0 0l4-4m-4 4l-4-4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Find counter-arguments
                </button>
                <button
                  type="button"
                  className="lookup-button lookup-button-sm casefile-export-button"
                  disabled={exporting}
                  onClick={handleExportCaseFile}
                >
                  {exporting ? (
                    <>
                      <span className="button-spinner" aria-hidden="true" />
                      Generating file…
                    </>
                  ) : (
                    `Export ${caseFileCases.length} case${caseFileCases.length > 1 ? "s" : ""}`
                  )}
                </button>
                <button
                  type="button"
                  className="lookup-button lookup-button-outline lookup-button-sm"
                  disabled={exporting}
                  onClick={() => {
                    setCaseFileCases([]);
                    setExportError("");
                  }}
                >
                  Clear
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
