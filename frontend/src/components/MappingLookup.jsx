import { useState } from "react";

const API_BASE = "http://localhost:8000";

export default function MappingLookup() {
  const [direction, setDirection] = useState("ipc");
  const [section, setSection] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  async function handleLookup(event) {
    event.preventDefault();
    const trimmed = section.trim();
    if (!trimmed) {
      setError("Enter a section number.");
      setResult(null);
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);

    const path =
      direction === "ipc"
        ? `/mapping/ipc/${encodeURIComponent(trimmed)}`
        : `/mapping/bns/${encodeURIComponent(trimmed)}`;

    try {
      const response = await fetch(`${API_BASE}${path}`);
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `Lookup failed (${response.status})`);
      }
      setResult(await response.json());
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="lookup-page">
      <h1>IPC–BNS Mapping</h1>
      <p className="lookup-lead">
        Look up the corresponding section under the Bharatiya Nyaya Sanhita (BNS)
        or Indian Penal Code (IPC).
      </p>

      <form className="lookup-form" onSubmit={handleLookup}>
        <div className="lookup-controls">
          <label className="lookup-field">
            <span className="lookup-label">Direction</span>
            <select
              className="lookup-select"
              value={direction}
              onChange={(event) => setDirection(event.target.value)}
            >
              <option value="ipc">IPC → BNS</option>
              <option value="bns">BNS → IPC</option>
            </select>
          </label>

          <label className="lookup-field lookup-field-grow">
            <span className="lookup-label">
              {direction === "ipc" ? "IPC section" : "BNS section"}
            </span>
            <input
              className="lookup-input"
              type="text"
              value={section}
              onChange={(event) => setSection(event.target.value)}
              placeholder={direction === "ipc" ? "e.g. 302" : "e.g. 101"}
            />
          </label>

          <button className="lookup-button" type="submit" disabled={loading}>
            {loading ? "Looking up…" : "Look up"}
          </button>
        </div>
      </form>

      {error && <p className="lookup-message lookup-error">{error}</p>}

      {result && (
        <article className="lookup-result">
          <h2>{result.title}</h2>
          <dl className="lookup-details">
            <div>
              <dt>IPC section</dt>
              <dd>{result.ipc_section}</dd>
            </div>
            <div>
              <dt>BNS section</dt>
              <dd>{result.bns_section}</dd>
            </div>
          </dl>
          {result.notes && <p className="lookup-notes">{result.notes}</p>}
        </article>
      )}
    </section>
  );
}
