import { useState } from "react";
import LoadingSpinner, { ResultSkeletonList } from "./LoadingSpinner.jsx";

const API_BASE = "http://localhost:8000";

function VerifiedIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function WarningIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path
        d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
const QA_RESULT_LIMIT = 10;

function uniqueCaseNames(caseNames = []) {
  return [...new Set(caseNames.filter(Boolean))];
}

export default function QuestionPage() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  async function handleAsk(event) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) {
      setError("Enter a legal research question.");
      setResult(null);
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);

    try {
      const response = await fetch(`${API_BASE}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed, n_results: QA_RESULT_LIMIT }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `Question failed (${response.status})`);
      }
      setResult(await response.json());
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  const retrievedSources = uniqueCaseNames(result?.retrieved_sources);
  const unverifiedCitations = result?.unverified_citations || [];

  return (
    <section className="lookup-page">
      <h1>Ask a Question</h1>
      <p className="lookup-lead">
        Ask about the judgment corpus. Answers are grounded in retrieved cases and
        checked against the cases supplied as context.
      </p>

      <form className="lookup-form" onSubmit={handleAsk}>
        <div className="form-card question-controls">
          <label className="lookup-field lookup-field-grow">
            <span className="lookup-label">Legal research question</span>
            <textarea
              className="lookup-input question-input"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="e.g. When does the right of private defence exceed reasonable force?"
              rows="4"
            />
          </label>

          <button className="lookup-button" type="submit" disabled={loading}>
            {loading ? (
              <>
                <span className="button-spinner" aria-hidden="true" />
                Preparing answer…
              </>
            ) : (
              "Ask question"
            )}
          </button>
        </div>
      </form>

      {loading && (
        <>
          <LoadingSpinner label="Retrieving context and generating answer…" />
          <ResultSkeletonList count={2} />
        </>
      )}

      {error && <p className="lookup-message lookup-error">{error}</p>}

      {result && (
        <article className="question-result">
          <div
            className={`verification-banner verification-banner-enter${
              result.verified
                ? " verification-banner-verified"
                : " verification-banner-unverified"
            }`}
            role="status"
          >
            <span className="verification-icon" aria-hidden="true">
              {result.verified ? <VerifiedIcon /> : <WarningIcon />}
            </span>
            <div className="verification-content">
              <strong>{result.verified ? "Verified" : "Unverified citation warning"}</strong>
              <span>
                {result.verified
                  ? "All detected case citations appear in the retrieved context."
                  : "One or more cited cases could not be verified against the retrieved context."}
              </span>
            </div>
          </div>

          <section className="question-section">
            <h2>Answer</h2>
            <p className="question-answer">{result.answer}</p>
          </section>

          {unverifiedCitations.length > 0 && (
            <section className="question-section question-warning">
              <h2>Unverified citations</h2>
              <ul className="question-list">
                {unverifiedCitations.map((citation) => (
                  <li key={citation}>{citation}</li>
                ))}
              </ul>
            </section>
          )}

          <section className="question-section">
            <h2>Retrieved sources</h2>
            {retrievedSources.length > 0 ? (
              <ul className="question-list">
                {retrievedSources.map((caseName) => (
                  <li key={caseName}>{caseName}</li>
                ))}
              </ul>
            ) : (
              <p className="question-empty">No judgment chunks were available as context.</p>
            )}
          </section>
        </article>
      )}
    </section>
  );
}
