import { useState } from "react";
import LoadingSpinner, { ResultSkeletonList } from "./components/LoadingSpinner.jsx";
import { authFetch } from "./api";

const API_BASE = "http://localhost:8000";
const ALLOWED_EXTENSIONS = [".pdf", ".txt"];

function isAllowedFile(file) {
  if (!file?.name) {
    return false;
  }
  const lowerName = file.name.toLowerCase();
  return ALLOWED_EXTENSIONS.some((extension) => lowerName.endsWith(extension));
}

function formatErrorDetail(detail) {
  if (!detail) {
    return null;
  }
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => item?.msg || item?.detail || String(item))
      .join("; ");
  }
  return String(detail);
}

/**
 * Render Gemini summary text that uses **Bold:** section headers.
 * Each "**Label:**" token starts a new visually distinct block.
 */
function SummaryBody({ text }) {
  // Split on markdown bold-label pattern: **Anything:** (preserving the delimiter)
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
      // Preamble text before the first header (rare but possible)
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

export default function DocumentUploadPage() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  // Document-level summary state
  const [docSummaryLoading, setDocSummaryLoading] = useState(false);
  const [docSummaryError, setDocSummaryError] = useState("");
  const [docSummary, setDocSummary] = useState(null);

  // Per-judgment card summary state: Map<case_name, { loading, error, summary }>
  const [cardSummaries, setCardSummaries] = useState(new Map());

  function handleFileChange(event) {
    const selected = event.target.files?.[0] || null;
    setFile(selected);
    setError("");
    setResult(null);
    setDocSummary(null);
    setDocSummaryError("");
    setCardSummaries(new Map());

    if (selected && !isAllowedFile(selected)) {
      setError("Only .pdf and .txt files are supported.");
      setFile(null);
      event.target.value = "";
    }
  }

  async function handleUpload(event) {
    event.preventDefault();

    if (!file) {
      setError("Choose a .pdf or .txt file to upload.");
      setResult(null);
      return;
    }

    if (!isAllowedFile(file)) {
      setError("Only .pdf and .txt files are supported.");
      setResult(null);
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);
    setDocSummary(null);
    setDocSummaryError("");
    setCardSummaries(new Map());

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await authFetch(`${API_BASE}/documents/upload`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(
          formatErrorDetail(body?.detail) || `Upload failed (${response.status})`,
        );
      }
      setResult(await response.json());
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSummarizeDocument() {
    if (!result?.extracted_text) return;
    setDocSummaryLoading(true);
    setDocSummaryError("");
    setDocSummary(null);

    try {
      const response = await authFetch(`${API_BASE}/documents/summarize-uploaded`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ extracted_text: result.extracted_text }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(
          formatErrorDetail(body?.detail) ||
            `Summarization failed (${response.status})`,
        );
      }
      const data = await response.json();
      setDocSummary(data.summary);
    } catch (err) {
      setDocSummaryError(err.message || "Something went wrong.");
    } finally {
      setDocSummaryLoading(false);
    }
  }

  function setCardState(caseName, patch) {
    setCardSummaries((prev) => {
      const next = new Map(prev);
      next.set(caseName, { ...(prev.get(caseName) ?? {}), ...patch });
      return next;
    });
  }

  async function handleSummarizeJudgment(caseName) {
    setCardState(caseName, { loading: true, error: "", summary: null });

    try {
      const encoded = encodeURIComponent(caseName);
      const response = await authFetch(
        `${API_BASE}/judgments/${encoded}/summary`,
      );
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(
          formatErrorDetail(body?.detail) ||
            `Summary failed (${response.status})`,
        );
      }
      const data = await response.json();
      setCardState(caseName, { loading: false, summary: data.summary });
    } catch (err) {
      setCardState(caseName, {
        loading: false,
        error: err.message || "Something went wrong.",
      });
    }
  }

  const relatedJudgments = result?.related_judgments || [];

  return (
    <section className="lookup-page">
      <h1>Document upload</h1>
      <p className="lookup-lead">
        Upload a legal document to extract its text and find related judgments
        from the corpus.
      </p>

      <form className="lookup-form" onSubmit={handleUpload}>
        <div className="form-card document-controls">
          <label className="lookup-field lookup-field-grow">
            <span className="lookup-label">Document (.pdf or .txt)</span>
            <input
              className="lookup-input document-file-input"
              type="file"
              accept=".pdf,.txt"
              onChange={handleFileChange}
            />
          </label>

          <button
            className="lookup-button"
            type="submit"
            disabled={loading || !file}
          >
            {loading ? (
              <>
                <span className="button-spinner" aria-hidden="true" />
                Uploading…
              </>
            ) : (
              "Upload"
            )}
          </button>
        </div>
      </form>

      {loading && (
        <>
          <LoadingSpinner label="Extracting text and finding related judgments…" />
          <ResultSkeletonList count={3} />
        </>
      )}

      {error && <p className="lookup-message lookup-error">{error}</p>}

      {!loading && result && (
        <article className="document-result">
          <p className="document-summary">
            <strong>{result.filename}</strong>
            {" · "}
            {result.char_count.toLocaleString()} characters extracted
          </p>

          {/* ── Extracted text + Summarize Document button ── */}
          <div className="document-extract-area">
            <details className="document-extract">
              <summary className="document-extract-summary">
                View extracted text
              </summary>
              <pre className="document-extract-text">{result.extracted_text}</pre>
            </details>

            <div className="document-summarize-row">
              <button
                className="lookup-button lookup-button-outline"
                type="button"
                disabled={docSummaryLoading}
                onClick={handleSummarizeDocument}
              >
                {docSummaryLoading ? (
                  <>
                    <span className="button-spinner button-spinner-dark" aria-hidden="true" />
                    Summarizing…
                  </>
                ) : (
                  "Summarize document"
                )}
              </button>
            </div>

            {docSummaryError && (
              <p className="lookup-message lookup-error">{docSummaryError}</p>
            )}

            {docSummaryLoading && (
              <LoadingSpinner label="Generating AI summary…" />
            )}

            {docSummary && !docSummaryLoading && (
              <div className="ai-summary-card ai-summary-card-enter">
                <p className="ai-summary-label">AI Summary</p>
                <SummaryBody text={docSummary} />
              </div>
            )}
          </div>

          {/* ── Related judgments ── */}
          <section className="document-related">
            <h2>Related judgments</h2>

            {relatedJudgments.length === 0 ? (
              <p className="lookup-message">No closely related judgments found.</p>
            ) : (
              <ul className="search-results">
                {relatedJudgments.map((judgment, index) => {
                  const cardState = cardSummaries.get(judgment.case_name) ?? {};
                  return (
                    <li
                      key={judgment.case_name}
                      className="search-result search-result-enter"
                      style={{ animationDelay: `${index * 75}ms` }}
                    >
                      <div className="search-result-header">
                        <h3>{judgment.case_name}</h3>
                        <span className="match-count-badge">
                          {judgment.match_count}{" "}
                          {judgment.match_count === 1 ? "match" : "matches"}
                        </span>
                      </div>
                      <p className="search-meta">
                        {judgment.court}
                        {judgment.year ? ` · ${judgment.year}` : ""}
                      </p>
                      {judgment.ipc_sections?.length > 0 && (
                        <p className="search-sections">
                          IPC: {judgment.ipc_sections.join(", ")}
                        </p>
                      )}
                      <p className="search-snippet">{judgment.snippet}</p>

                      {/* Per-card Summarize button */}
                      <div className="card-summarize-row">
                        <button
                          className="lookup-button lookup-button-outline lookup-button-sm"
                          type="button"
                          disabled={cardState.loading}
                          onClick={() =>
                            handleSummarizeJudgment(judgment.case_name)
                          }
                        >
                          {cardState.loading ? (
                            <>
                              <span
                                className="button-spinner button-spinner-dark"
                                aria-hidden="true"
                              />
                              Summarizing…
                            </>
                          ) : (
                            "Summarize"
                          )}
                        </button>
                      </div>

                      {cardState.error && (
                        <p className="lookup-message lookup-error card-summary-error">
                          {cardState.error}
                        </p>
                      )}

                      {cardState.loading && (
                        <LoadingSpinner label="Generating AI summary…" />
                      )}

                      {cardState.summary && !cardState.loading && (
                        <div className="ai-summary-card ai-summary-card-enter ai-summary-card-inline">
                          <p className="ai-summary-label">AI Summary</p>
                          <SummaryBody text={cardState.summary} />
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </article>
      )}
    </section>
  );
}
