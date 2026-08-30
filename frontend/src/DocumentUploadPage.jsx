import { useState } from "react";

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

export default function DocumentUploadPage() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  function handleFileChange(event) {
    const selected = event.target.files?.[0] || null;
    setFile(selected);
    setError("");
    setResult(null);

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

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(`${API_BASE}/documents/upload`, {
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

  const relatedJudgments = result?.related_judgments || [];

  return (
    <section className="lookup-page">
      <h1>Document Upload</h1>
      <p className="lookup-lead">
        Upload a legal document to extract its text and find related judgments
        from the corpus.
      </p>

      <form className="lookup-form" onSubmit={handleUpload}>
        <div className="document-controls">
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
            {loading ? "Uploading…" : "Upload"}
          </button>
        </div>
      </form>

      {error && <p className="lookup-message lookup-error">{error}</p>}

      {result && (
        <article className="document-result">
          <p className="document-summary">
            <strong>{result.filename}</strong>
            {" · "}
            {result.char_count.toLocaleString()} characters extracted
          </p>

          <details className="document-extract">
            <summary className="document-extract-summary">View extracted text</summary>
            <pre className="document-extract-text">{result.extracted_text}</pre>
          </details>

          <section className="document-related">
            <h2>Related judgments</h2>

            {relatedJudgments.length === 0 ? (
              <p className="lookup-message">No closely related judgments found.</p>
            ) : (
              <ul className="search-results">
                {relatedJudgments.map((judgment) => (
                  <li key={judgment.case_name} className="search-result">
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
                  </li>
                ))}
              </ul>
            )}
          </section>
        </article>
      )}
    </section>
  );
}
