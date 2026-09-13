import { useEffect, useRef, useState } from "react";
import LoadingSpinner, { ResultSkeletonList } from "./LoadingSpinner.jsx";
import { API_BASE, authFetch } from "../api";
import {
  createSpeechRecognition,
  isSpeechRecognitionSupported,
  isSpeechSynthesisSupported,
  speakText,
  stopSpeaking,
} from "../utils/speech.js";

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

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
      <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
      <path d="M19 10v2a7 7 0 01-14 0v-2M12 19v4M8 23h8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function SpeakerIcon({ isSpeaking }) {
  if (isSpeaking) {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
        <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
      <path d="M11 5L6 9H2v6h4l5 4V5z" strokeLinejoin="round" />
      <path d="M15.54 8.46a5 5 0 010 7.07M19.07 4.93a10 10 0 010 14.14" strokeLinecap="round" />
    </svg>
  );
}

function ImageUploadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <polyline points="21 15 16 10 5 21" strokeLinejoin="round" strokeLinecap="round" />
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

  // Voice Input (SpeechRecognition) state
  const speechSupported = isSpeechRecognitionSupported();
  const [isListening, setIsListening] = useState(false);
  const [voiceTarget, setVoiceTarget] = useState(null); // 'single' or 'student'
  const [voiceError, setVoiceError] = useState("");
  const activeRecognitionRef = useRef(null);

  // Voice Output (SpeechSynthesis) state
  const [activeSpeakingId, setActiveSpeakingId] = useState(null);

  const chatBottomRef = useRef(null);

  // Image explain state (public standalone + student inline)
  const [imageLoading, setImageLoading] = useState(false);
  const [imageResult, setImageResult] = useState(null); // { filename, explanation, error }
  const studentImageInputRef = useRef(null);
  const publicImageInputRef = useRef(null);

  // Cleanup speech synthesis and recognition on unmount
  useEffect(() => {
    return () => {
      stopSpeaking();
      if (activeRecognitionRef.current) {
        try {
          activeRecognitionRef.current.abort();
        } catch {}
      }
    };
  }, []);

  function handleToggleReadAloud(id, text) {
    if (!isSpeechSynthesisSupported()) return;

    if (activeSpeakingId === id) {
      stopSpeaking();
      setActiveSpeakingId(null);
    } else {
      setActiveSpeakingId(id);
      speakText(
        text,
        () => setActiveSpeakingId(id),
        () => setActiveSpeakingId(null)
      );
    }
  }

  function handleStartVoiceInput(targetMode) {
    if (!speechSupported) return;

    setVoiceError("");

    if (isListening) {
      if (activeRecognitionRef.current) {
        try {
          activeRecognitionRef.current.stop();
        } catch {}
      }
      setIsListening(false);
      setVoiceTarget(null);
      return;
    }

    const recognition = createSpeechRecognition();
    if (!recognition) return;

    activeRecognitionRef.current = recognition;
    setIsListening(true);
    setVoiceTarget(targetMode);

    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((r) => r[0]?.transcript || "")
        .join(" ")
        .trim();

      if (transcript) {
        if (targetMode === "student") {
          setStudentInput((prev) => (prev ? `${prev} ${transcript}` : transcript));
        } else {
          setQuestion((prev) => (prev ? `${prev} ${transcript}` : transcript));
        }
      }
    };

    recognition.onerror = (event) => {
      // Ensure listening state is immediately cleared so button does not stay stuck
      setIsListening(false);
      activeRecognitionRef.current = null;

      const err = event.error || "";
      if (err === "not-allowed" || err === "permission-denied" || err === "service-not-allowed") {
        setVoiceError(
          "Microphone access is blocked. Enable it in your browser's site settings (click the lock icon in the address bar), then reload the page."
        );
      } else if (err === "no-speech") {
        setVoiceError("No speech was detected. Please try again.");
      } else if (err === "network") {
        setVoiceError("Network error occurred during speech recognition. Please check your connection and try again.");
      } else if (err !== "aborted") {
        setVoiceError("Voice input didn't work, please try again.");
      }
    };

    recognition.onend = () => {
      setIsListening(false);
      activeRecognitionRef.current = null;
    };

    try {
      recognition.start();
    } catch (err) {
      setIsListening(false);
      activeRecognitionRef.current = null;
      setVoiceError("Voice input didn't work, please try again.");
    }
  }

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

  // Shared image-explain handler used by both student and public personas
  async function handleExplainImage(file, targetPersona) {
    if (!file) return;
    const suffix = file.name.toLowerCase().split(".").pop();
    if (!["jpg", "jpeg", "png"].includes(suffix)) return;

    if (targetPersona === "public") {
      setImageLoading(true);
      setImageResult(null);
    } else if (targetPersona === "student") {
      setStudentLoading(true);
      setStudentError("");
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await authFetch(`${API_BASE}/documents/explain-image`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `Upload failed (${response.status})`);
      }
      const data = await response.json();

      if (targetPersona === "public") {
        setImageResult(data);
      } else if (targetPersona === "student") {
        // Inject as a chat turn: user bubble = "[Uploaded image: filename]",
        // AI bubble = explanation (or error text if present)
        const answerText = data.error
          ? data.error
          : data.explanation || "No explanation was returned.";
        setConversationHistory((prev) => [
          ...prev,
          {
            question: `[Uploaded image: ${data.filename}]`,
            answer: answerText,
            responseData: null, // no citation/source metadata for this flow
          },
        ]);
      }
    } catch (err) {
      if (targetPersona === "public") {
        setImageResult({ error: err.message || "Something went wrong." });
      } else if (targetPersona === "student") {
        setStudentError(err.message || "Image upload failed. Please try again.");
      }
    } finally {
      if (targetPersona === "public") setImageLoading(false);
      if (targetPersona === "student") setStudentLoading(false);
    }
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
                  <div className="qa-chat-bubble-header">
                    <div className="qa-chat-bubble-label">Legal Assistant</div>
                    {isSpeechSynthesisSupported() && (
                      <button
                        type="button"
                        className={`qa-speak-button${activeSpeakingId === `student-${idx}` ? " qa-speak-button-active" : ""}`}
                        onClick={() => handleToggleReadAloud(`student-${idx}`, turn.answer)}
                        title={activeSpeakingId === `student-${idx}` ? "Stop speaking" : "Read aloud"}
                        aria-label={activeSpeakingId === `student-${idx}` ? "Stop speaking" : "Read aloud"}
                      >
                        <SpeakerIcon isSpeaking={activeSpeakingId === `student-${idx}`} />
                        <span>{activeSpeakingId === `student-${idx}` ? "Stop" : "Read aloud"}</span>
                      </button>
                    )}
                  </div>

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
              <div className="qa-student-footer-left">
                <button
                  type="button"
                  className={`voice-mic-button${isListening && voiceTarget === "student" ? " voice-mic-button-listening" : ""}`}
                  disabled={!speechSupported}
                  onClick={() => handleStartVoiceInput("student")}
                  title={
                    !speechSupported
                      ? "Voice input isn't supported in this browser - try Chrome or Edge."
                      : isListening && voiceTarget === "student"
                      ? "Listening... Click to stop"
                      : "Speak your question"
                  }
                  aria-label={
                    !speechSupported
                      ? "Voice input isn't supported in this browser - try Chrome or Edge."
                      : isListening && voiceTarget === "student"
                      ? "Listening... Click to stop"
                      : "Speak your question"
                  }
                >
                  <MicIcon />
                  {isListening && voiceTarget === "student" ? (
                    <span className="voice-mic-pulse-text">Listening…</span>
                  ) : null}
                </button>

                {/* Hidden file input for image explain */}
                <input
                  ref={studentImageInputRef}
                  type="file"
                  accept=".jpg,.jpeg,.png"
                  className="sr-only-input"
                  aria-hidden="true"
                  tabIndex={-1}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = "";
                    if (file) handleExplainImage(file, "student");
                  }}
                />
                <button
                  type="button"
                  className="voice-mic-button image-upload-chat-button"
                  disabled={studentLoading}
                  onClick={() => studentImageInputRef.current?.click()}
                  title="Upload an image to explain"
                  aria-label="Upload an image to explain"
                >
                  <ImageUploadIcon />
                </button>

                <span className="qa-student-hint">Press Ctrl+Enter or click Send</span>
              </div>
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
            {voiceError && voiceTarget === "student" && (
              <p className="voice-input-error">{voiceError}</p>
            )}
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

          <div className="question-actions-row">
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

            {/* Voice input mic button with persona-specific prominence:
                For the PUBLIC persona, voice input provides a major accessibility and usability win 
                for citizens with lower typing proficiency or literacy barriers, so we provide a prominent 
                button with an adjacent "Ask by voice" label. For lawyers/judges, a sleek, compact button is used. */}
            <button
              type="button"
              className={`voice-mic-button${isPublic ? " voice-mic-button-public" : ""}${
                isListening && voiceTarget === "single" ? " voice-mic-button-listening" : ""
              }`}
              disabled={!speechSupported}
              onClick={() => handleStartVoiceInput("single")}
              title={
                !speechSupported
                  ? "Voice input isn't supported in this browser - try Chrome or Edge."
                  : isListening && voiceTarget === "single"
                  ? "Listening... Click to stop"
                  : isPublic
                  ? "Ask by voice"
                  : "Voice input"
              }
              aria-label={
                !speechSupported
                  ? "Voice input isn't supported in this browser - try Chrome or Edge."
                  : isListening && voiceTarget === "single"
                  ? "Listening... Click to stop"
                  : isPublic
                  ? "Ask by voice"
                  : "Voice input"
              }
            >
              <MicIcon />
              {isListening && voiceTarget === "single" ? (
                <span className="voice-mic-pulse-text">Listening…</span>
              ) : isPublic ? (
                <span className="voice-mic-label">Ask by voice</span>
              ) : null}
            </button>
          </div>

          {voiceError && voiceTarget === "single" && (
            <p className="voice-input-error">{voiceError}</p>
          )}
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
            <div className="question-answer-header">
              <h2>Answer</h2>
              {isSpeechSynthesisSupported() && (
                <button
                  type="button"
                  className={`qa-speak-button${activeSpeakingId === "single-answer" ? " qa-speak-button-active" : ""}`}
                  onClick={() => handleToggleReadAloud("single-answer", result.answer)}
                  title={activeSpeakingId === "single-answer" ? "Stop speaking" : "Read aloud"}
                  aria-label={activeSpeakingId === "single-answer" ? "Stop speaking" : "Read aloud"}
                >
                  <SpeakerIcon isSpeaking={activeSpeakingId === "single-answer"} />
                  <span>{activeSpeakingId === "single-answer" ? "Stop" : "Read aloud"}</span>
                </button>
              )}
            </div>
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

      {/* ── PUBLIC: Upload an image to understand ─────────────────── */}
      {isPublic && (
        <section className="image-explain-section">
          <h2 className="image-explain-heading">Upload a document to understand</h2>
          <p className="image-explain-lead">
            Take a photo of a legal notice, FIR, affidavit, or any printed document.
            We'll extract the text and explain it in plain language.
          </p>

          {/* Hidden file input */}
          <input
            ref={publicImageInputRef}
            type="file"
            accept=".jpg,.jpeg,.png"
            className="sr-only-input"
            aria-hidden="true"
            tabIndex={-1}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) handleExplainImage(file, "public");
            }}
          />

          <button
            type="button"
            className="lookup-button lookup-button-outline image-explain-upload-btn"
            disabled={imageLoading}
            onClick={() => publicImageInputRef.current?.click()}
          >
            {imageLoading ? (
              <>
                <span className="button-spinner button-spinner-dark" aria-hidden="true" />
                Analysing image…
              </>
            ) : (
              <>
                <ImageUploadIcon />
                Choose image (.jpg, .png)
              </>
            )}
          </button>

          {/* Disclaimer applies here too */}
          <div className="public-disclaimer-banner image-explain-disclaimer" role="note">
            <div className="public-disclaimer-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 16v-4m0-4h.01" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="public-disclaimer-text">
              <strong>Legal Information Notice:</strong> This explanation is for general
              understanding only, not legal advice. Consult a qualified lawyer for guidance
              on your specific situation.
            </div>
          </div>

          {/* Loading */}
          {imageLoading && (
            <LoadingSpinner label="Extracting and explaining document…" />
          )}

          {/* Result / Error */}
          {!imageLoading && imageResult && (
            <article className="image-explain-result">
              {imageResult.error ? (
                <p className="lookup-message lookup-error">{imageResult.error}</p>
              ) : (
                <>
                  <p className="image-explain-filename">{imageResult.filename}</p>
                  <div className="question-answer">{imageResult.explanation}</div>
                </>
              )}
            </article>
          )}
        </section>
      )}
    </section>
  );
}
