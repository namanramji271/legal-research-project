import { useEffect, useRef, useState } from "react";

const FEATURES = [
  {
    id: "mapping",
    title: "IPC–BNS mapping",
    description: "Look up bidirectional section correspondences under the new Bharatiya Nyaya Sanhita.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: "search",
    title: "Judgment search",
    description: "Search the curated corpus of murder, culpable homicide, and private-defence judgments.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="11" cy="11" r="6" />
        <path d="M20 20l-4-4" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: "question",
    title: "Ask a question",
    description: "Get citation-backed answers grounded in retrieved judgments, with verification safeguards.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 18h.01M8.5 8.5a3.5 3.5 0 117 0c0 2-2 2.5-2 3.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="12" cy="12" r="9" />
      </svg>
    ),
  },
  {
    id: "upload",
    title: "Document upload",
    description: "Upload a brief or memo to extract text and surface related precedent from the corpus.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 15V5m0 0l-3.5 3.5M12 5l3.5 3.5M5 19h14" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
];

const PIPELINE_STEPS = [
  {
    label: "Query",
    description: "Natural-language question or search text from the user.",
  },
  {
    label: "Embedding Model",
    description: "Sentence Transformers (MiniLM) encodes the query into a dense vector.",
  },
  {
    label: "Vector Search (ChromaDB)",
    description: "Retrieves the closest judgment chunks from the indexed corpus.",
  },
  {
    label: "LLM Generation (Gemini)",
    description: "Generates an answer grounded only in the retrieved context.",
  },
  {
    label: "Citation Verification",
    description: "Checks cited case names against the retrieved chunk set.",
  },
  {
    label: "Verified Answer",
    description: "Response returned with verification status and source list.",
  },
];

const EVAL_STATS = [
  { value: "48", label: "Curated judgments in the corpus" },
  { value: "533", label: "Indexed text chunks embedded and stored" },
  {
    value: "0",
    label: "Fabricated citations across 13 QA test questions (including 4 deliberately out-of-scope)",
  },
  { value: "0.733", label: "Mean reciprocal rank (MRR) on BM25 retrieval evaluation" },
  { value: "18", label: "IPC↔BNS section mappings implemented and tested" },
];

const TECH_STACK = [
  "FastAPI",
  "React",
  "ChromaDB",
  "Google Gemini",
  "Sentence Transformers (MiniLM / BGE-M3)",
  "SQLite",
];

const CARD_STAGGER_MS = 90;
const SECTION_STAGGER_MS = 80;

function useInView() {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element) {
      return undefined;
    }

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setVisible(true);
      return undefined;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -32px 0px" },
    );

    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return { ref, visible };
}

function PipelineConnector({ index, visible }) {
  return (
    <div
      className={`pipeline-connector${visible ? " pipeline-connector-visible" : ""}`}
      aria-hidden="true"
      style={{ "--connector-index": index }}
    >
      <svg className="pipeline-connector-line pipeline-connector-line-horizontal" viewBox="0 0 40 24">
        <path
          d="M2 12 H28 M22 7 L28 12 L22 17"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          pathLength="1"
        />
      </svg>
      <svg className="pipeline-connector-line pipeline-connector-line-vertical" viewBox="0 0 24 40">
        <path
          d="M12 2 V28 M7 22 L12 28 L17 22"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          pathLength="1"
        />
      </svg>
    </div>
  );
}

export default function DashboardPage({ onNavigate }) {
  const { ref: gridRef, visible: cardsVisible } = useInView();
  const { ref: pipelineRef, visible: pipelineVisible } = useInView();
  const { ref: statsRef, visible: statsVisible } = useInView();
  const { ref: stackRef, visible: stackVisible } = useInView();
  const { ref: contextRef, visible: contextVisible } = useInView();

  return (
    <section className="dashboard-page">
      {/* ── Zone 1: Product zone ── */}
      <div className="dashboard-product-zone">
        <header className="dashboard-hero">
          <h1 className="dashboard-headline">Legal Research Platform</h1>
          <p className="dashboard-intro">
            An AI-assisted research tool for Indian criminal law covering murder,
            culpable homicide, and private defence. Navigate bidirectional IPC–BNS
            section mapping, run semantic search over curated judgments, ask
            citation-backed questions with verification safeguards, or upload a
            document to find related precedent.
          </p>
        </header>

        <div
          ref={gridRef}
          className={`dashboard-grid${cardsVisible ? " dashboard-grid-visible" : ""}`}
        >
          {FEATURES.map((feature, index) => (
            <button
              key={feature.id}
              type="button"
              className="dashboard-card"
              style={
                cardsVisible ? { animationDelay: `${index * CARD_STAGGER_MS}ms` } : undefined
              }
              onClick={() => onNavigate(feature.id)}
            >
              <span className="dashboard-card-icon" aria-hidden="true">
                {feature.icon}
              </span>
              <span className="dashboard-card-body">
                <span className="dashboard-card-title">{feature.title}</span>
                <span className="dashboard-card-desc">{feature.description}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* ── Zone 2: Technical & evidence zone ── */}
      <section className="dashboard-technical-zone" aria-labelledby="technical-reference-title">
        <header className="dashboard-zone-header">
          <span className="dashboard-zone-eyebrow">Architecture &amp; evaluation</span>
          <h2 id="technical-reference-title" className="dashboard-zone-title">Technical reference</h2>
          <p className="dashboard-zone-lead">
            Pipeline architecture, empirical evaluation metrics, and implementation details for the underlying retrieval and verification engine.
          </p>
        </header>

        <section
          ref={pipelineRef}
          className={`dashboard-section dashboard-pipeline${
            pipelineVisible ? " dashboard-section-visible" : ""
          }`}
        >
          <h3 className="dashboard-section-title">How it works</h3>
          <p className="dashboard-section-lead">
            The question-answering pipeline from user query to a citation-verified response.
          </p>
          <ol className="pipeline-flow">
            {PIPELINE_STEPS.map((step, index) => (
              <li key={step.label} className="pipeline-flow-item">
                <article
                  className="pipeline-step"
                  style={
                    pipelineVisible
                      ? { animationDelay: `${index * SECTION_STAGGER_MS}ms` }
                      : undefined
                  }
                >
                  <span className="pipeline-step-index">{index + 1}</span>
                  <h4 className="pipeline-step-label">{step.label}</h4>
                  <p className="pipeline-step-desc">{step.description}</p>
                </article>
                {index < PIPELINE_STEPS.length - 1 ? (
                  <PipelineConnector index={index} visible={pipelineVisible} />
                ) : null}
              </li>
            ))}
          </ol>
        </section>

        <section
          ref={statsRef}
          className={`dashboard-section dashboard-stats${
            statsVisible ? " dashboard-section-visible" : ""
          }`}
        >
          <h3 className="dashboard-section-title">Evaluation results</h3>
          <p className="dashboard-section-lead">
            Measured outcomes from the project&apos;s retrieval and QA evaluation runs.
          </p>
          <dl className="stats-grid">
            {EVAL_STATS.map((stat, index) => (
              <div
                key={stat.label}
                className="stat-item"
                style={
                  statsVisible ? { animationDelay: `${index * SECTION_STAGGER_MS}ms` } : undefined
                }
              >
                <dt className="stat-value">{stat.value}</dt>
                <dd className="stat-label">{stat.label}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section
          ref={stackRef}
          className={`dashboard-section dashboard-stack${
            stackVisible ? " dashboard-section-visible" : ""
          }`}
        >
          <h3 className="dashboard-section-title">Tech stack</h3>
          <ul className="stack-grid">
            {TECH_STACK.map((item, index) => (
              <li
                key={item}
                className="stack-item"
                style={
                  stackVisible ? { animationDelay: `${index * SECTION_STAGGER_MS}ms` } : undefined
                }
              >
                {item}
              </li>
            ))}
          </ul>
        </section>

        <section
          ref={contextRef}
          className={`dashboard-section dashboard-context${
            contextVisible ? " dashboard-section-visible" : ""
          }`}
        >
          <h3 className="dashboard-section-title">Context</h3>
          <p className="dashboard-context-text">
            The 2024 transition from the Indian Penal Code (IPC) to the Bharatiya Nyaya
            Sanhita (BNS) requires legal professionals to work across both frameworks
            simultaneously. Existing keyword-based legal search tools often fail to
            retrieve conceptually related judgments when different terminology is used
            for the same legal concept — a gap this platform addresses through semantic
            retrieval and bidirectional section mapping.
          </p>
        </section>
      </section>
    </section>
  );
}
