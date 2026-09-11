import { useEffect, useRef, useState } from "react";
import LoadingSpinner, { ResultSkeletonList } from "./LoadingSpinner.jsx";
import { API_BASE, authFetch } from "../api";

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

const EXAMPLE_QUESTIONS = [
  "When does the right of private defence exceed reasonable force?",
  "What distinguishes murder from culpable homicide not amounting to murder?",
  "How is common intention proven under Section 34?",
];

const STUDENT_FOLLOW_UP_SUGGESTIONS = [
  "Can you give an example?",
  "What's the difference between this and related offences?",
  "Why did the court decide this way?",
];

function uniqueCaseNames(caseNames = []) {
  return [...new Set(caseNames.filter(Boolean))];
}

export default function QuestionPage({ auth }) {
  const role = auth?.role || "lawyer";
  const isStudent = role === "student";
  const isPublic = role === "public";

  // State for single-turn (lawyer, judge, public)
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  // State for multi-turn chat (student)
  // conversationHistory: [{ question: string, answer: string, responseData?: object }]
  const [conversationHistory, setConversationHistory] = useState([]);
  const [studentInput, setStudentInput] = useState("");
  const [studentLoading, setStudentLoading] = useState(false);
  const [studentError, setStudentError] = useState("");

  const chatBottomRef = useRef(null);

  useEffect(() => {
    if (isStudent && conversationHistory.length > 0) {
      chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [conversationHistory, studentLoading, isStudent]);

  // Standard one-shot ask for Lawyer/Judge and Public
  async function executeAsk(questionText) {
    const trimmed = questionText.trim();
    if (!trimmed) {
      setError("Enter a legal research question.");
      setResult(null);
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);

    try {
      const response = await authFetch(`${API_BASE}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: trimmed,
          n_results: QA_RESULT_LIMIT,
          persona: role,
          conversation_history: [],
        }),
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

  function handleAsk(event) {
    event.preventDefault();
    executeAsk(question);
  }

  function handleChipClick(examplePrompt) {
    setQuestion(examplePrompt);
    executeAsk(examplePrompt);
  }

  // Student multi-turn ask
  async function executeStudentAsk(questionText) {
    const trimmed = questionText.trim();
    if (!trimmed) return;

    // Send the CURRENT full conversation_history array (before adding new turn)
    const historyPayload = conversationHistory.map((turn) => ({
      question: turn.question,
      answer: turn.answer,
    }));

    setStudentLoading(true);
    setStudentError("");
    setStudentInput("");

    try {
      const response = await authFetch(`${API_BASE}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: trimmed,
          n_results: QA_RESULT_LIMIT,
          persona: "student",
          conversation_history: historyPayload,
        }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `Question failed (${response.status})`);
      }

      const data = await response.json();
      setConversationHistory((prev) => [
        ...prev,
        {
          question: trimmed,
          answer: data.answer,
          responseData: data,
        },
      ]);
    } catch (err) {
      setStudentError(err.message || "Something went wrong.");
    } finally {
      setStudentLoading(false);
    }
  }

  function handleStudentSubmit(e) {
    e.preventDefault();
    executeStudentAsk(studentInput);
  }

  function handleClearConversation() {
    setConversationHistory([]);
    setStudentInput("");
    setStudentError("");
  }

  /* -------------------------------------------------------------
     RENDER: STUDENT PERSONA (Multi-turn Chat Thread)
  ------------------------------------------------------------- */
  if (isStudent) {
    return (
      <section className="lookup-page qa-student-page">
        <div className="qa-student-header">
          <div>
            <h1>Student Legal Assistant</h1>
            <p className="lookup-lead">
              Interactive legal tutor with contextual multi-turn conversation and practical explanations.
            </p>
          </div>
          {conversationHistory.length > 0 && (
            <button
              type="button"
              className="lookup-button lookup-button-outline lookup-button-sm qa-clear-button"
              onClick={handleClearConversation}
            >
              Clear conversation
            </button>
          )}
        </div>

        <p className="corpus-scope-note">
          Corpus scope: Murder &amp; Culpable Homicide (IPC 299–304) · Private Defence (IPC 96–106)
        </p>

        {/* Chat Thread Container */}
        <div className="qa-chat-thread" role="log" aria-live="polite">
          {conversationHistory.length === 0 && !studentLoading && (
            <div className="qa-chat-empty">
              <p className="qa-chat-empty-title">Ask a question to start exploring</p>
              <p className="qa-chat-empty-desc">
                Learn key legal principles, compare doctrines, and ask follow-up questions in natural language.
              </p>
              <div className="query-chips-group">
                <span className="query-chips-label">Suggested questions</span>
                <div className="query-chips">
                  {EXAMPLE_QUESTIONS.map((example) => (
                    <button
                      key={example}
                      type="button"
                      className="query-chip"
                      onClick={() => executeStudentAsk(example)}
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {conversationHistory.map((turn, idx) => {
            const resp = turn.responseData;
            const retrievedSources = uniqueCaseNames(resp?.retrieved_sources);
            const unverifiedCitations = resp?.unverified_citations || [];

            return (
              <div key={idx} className="qa-chat-turn">
                {/* User Question Bubble */}
                <div className="qa-chat-bubble qa-chat-bubble-user">
                  <div className="qa-chat-bubble-label">You</div>
                  <div className="qa-chat-bubble-text">{turn.question}</div>
                </div>

                {/* AI Answer Bubble */}
                <div className="qa-chat-bubble qa-chat-bubble-assistant">
                  <div className="qa-chat-bubble-label">Legal Assistant</div>

                  {/* Verification Banner */}
                  {resp && (
                    <div
                      className={`verification-banner verification-banner-enter qa-chat-verification${
                        resp.verified
                          ? " verification-banner-verified"
                          : " verification-banner-unverified"
                      }`}
                      role="status"
                    >
                      <span className="verification-icon" aria-hidden="true">
                        {resp.verified ? <VerifiedIcon /> : <WarningIcon />}
                      </span>
                      <div className="verification-content">
                        <strong>{resp.verified ? "Verified" : "Unverified citation warning"}</strong>
                        <span>
                          {resp.verified
                            ? "All detected case citations appear in the retrieved context."
                            : "One or more cited cases could not be verified against the retrieved context."}
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Answer Text */}
                  <div className="question-answer qa-chat-answer">{turn.answer}</div>

                  {/* Unverified citations */}
                  {unverifiedCitations.length > 0 && (
                    <section className="question-section question-warning qa-chat-sources">
                      <h2>Unverified citations</h2>
                      <ul className="question-list">
                        {unverifiedCitations.map((citation) => (
                          <li key={citation}>{citation}</li>
                        ))}
                      </ul>
                    </section>
                  )}

                  {/* Sources Used / Retrieved Sources */}
                  {retrievedSources.length > 0 && (
                    <section className="question-section qa-chat-sources">
                      <h2>Retrieved sources</h2>
                      <ul className="question-list">
                        {retrievedSources.map((caseName) => (
                          <li key={caseName}>{caseName}</li>
                        ))}
                      </ul>
                    </section>
                  )}

                  {/* Suggested Follow-ups */}
                  <div className="qa-followups-container">
                    <span className="qa-followups-label">Suggested follow-ups</span>
                    <div className="qa-followups-chips">
                      {STUDENT_FOLLOW_UP_SUGGESTIONS.map((chip) => (
                        <button
                          key={chip}
                          type="button"
                          className="query-chip qa-followup-chip"
                          disabled={studentLoading}
                          onClick={() => executeStudentAsk(chip)}
                        >
                          {chip}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}

          {studentLoading && (
            <div className="qa-chat-turn">
              <div className="qa-chat-bubble qa-chat-bubble-assistant qa-chat-bubble-loading">
                <LoadingSpinner label="Formulating answer with research context…" />
              </div>
            </div>
          )}

          {studentError && (
            <p className="lookup-message lookup-error qa-chat-error">{studentError}</p>
          )}

          <div ref={chatBottomRef} />
        </div>

        {/* Input bar */}
        <form className="qa-student-input-form" onSubmit={handleStudentSubmit}>
          <div className="form-card qa-student-controls">
            <textarea
              className="lookup-input question-input qa-student-textarea"
              value={studentInput}
              onChange={(e) => setStudentInput(e.target.value)}
              placeholder="Ask a question or request clarification on the discussion…"
              rows="3"
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  executeStudentAsk(studentInput);
                }
              }}
            />
            <div className="qa-student-form-footer">
              <span className="qa-student-hint">Press Ctrl+Enter or click Send</span>
              <button
                className="lookup-button lookup-button-sm"
                type="submit"
                disabled={studentLoading || !studentInput.trim()}
              >
                {studentLoading ? (
                  <>
                    <span className="button-spinner" aria-hidden="true" />
                    Thinking…
                  </>
                ) : (
                  "Send"
                )}
              </button>
            </div>
          </div>
        </form>
      </section>
    );
  }

  /* -------------------------------------------------------------
     RENDER: PUBLIC PERSONA & LAWYER/JUDGE PERSONA
  ------------------------------------------------------------- */
  const retrievedSources = uniqueCaseNames(result?.retrieved_sources);
  const unverifiedCitations = result?.unverified_citations || [];

  return (
    <section className="lookup-page">
      {/* Public Disclaimer Banner */}
      {isPublic && (
        <div className="public-disclaimer-banner" role="note">
          <div className="public-disclaimer-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <path d="M12 16v-4m0-4h.01" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="public-disclaimer-text">
            <strong>Legal Information Notice:</strong> This tool provides general legal information,
            not legal advice. For guidance on your specific situation, please consult a qualified lawyer.
          </div>
        </div>
      )}

      <h1>Ask a question</h1>
      <p className="lookup-lead">
        {isPublic
          ? "Ask questions about legal concepts in plain language. Answers explain principles without complex jargon."
          : "Ask about the judgment corpus. Answers are grounded in retrieved cases and checked against the cases supplied as context."}
      </p>

      <p className="corpus-scope-note">
        Corpus scope: Murder &amp; Culpable Homicide (IPC 299–304) · Private Defence (IPC 96–106)
      </p>

      <form className="lookup-form" onSubmit={handleAsk}>
        <div className="form-card question-controls">
          <label className="lookup-field lookup-field-grow">
            <span className="lookup-label">
              {isPublic ? "Your question" : "Legal research question"}
            </span>
            <textarea
              className="lookup-input question-input"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder={
                isPublic
                  ? "e.g. When is a person allowed to defend themselves or their family?"
                  : "e.g. When does the right of private defence exceed reasonable force?"
              }
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

        {!loading && !result && (
          <div className="query-chips-group">
            <span className="query-chips-label">Suggested questions</span>
            <div className="query-chips">
              {EXAMPLE_QUESTIONS.map((example) => (
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
          <LoadingSpinner label="Retrieving context and generating answer…" />
          <ResultSkeletonList count={2} />
        </>
      )}

      {error && <p className="lookup-message lookup-error">{error}</p>}

      {result && (
        <article className="question-result">
          {/* Lawyer/Judge show verification banner; Public hides it */}
          {!isPublic && (
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
          )}

          <section className="question-section">
            <h2>Answer</h2>
            <p className="question-answer">{result.answer}</p>
          </section>

          {/* Lawyer/Judge show unverified citations & retrieved sources; Public hides them */}
          {!isPublic && unverifiedCitations.length > 0 && (
            <section className="question-section question-warning">
              <h2>Unverified citations</h2>
              <ul className="question-list">
                {unverifiedCitations.map((citation) => (
                  <li key={citation}>{citation}</li>
                ))}
              </ul>
            </section>
          )}

          {!isPublic && (
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
          )}
        </article>
      )}
    </section>
  );
}

