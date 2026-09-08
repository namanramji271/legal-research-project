import { useState } from "react";
import { API_BASE } from "../api";

export default function LoginPage({ onLogin, onSwitchToSignup }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmed = username.trim();
    if (!trimmed || !password) {
      setError("Please enter both username and password.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: trimmed,
          password,
        }),
      });

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        throw new Error(data?.detail || "Invalid username or password");
      }


      const authData = {
        ...data,
        token: data.access_token,
      };
      localStorage.setItem("auth", JSON.stringify(authData));

      if (onLogin) {
        onLogin(authData);
      }
    } catch (err) {
      setError(err.message || "Failed to log in.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-wrapper">
      <div className="auth-card">
        <div className="auth-header">
          <div className="auth-brand">
            <svg
              className="sidebar-brand-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              aria-hidden="true"
            >
              <path d="M6 4h12v16H6z" />
              <path d="M9 8h6M9 12h6M9 16h4" strokeLinecap="round" />
            </svg>
            <span className="sidebar-wordmark">Legal Research</span>
          </div>
          <h1>Log in</h1>
          <p className="auth-lead">
            Sign in with your credentials to access the legal research platform.
          </p>
        </div>


        {error && (
          <div className="auth-field-error-box auth-general-error" role="alert">
            <svg
              className="auth-error-icon"
              viewBox="0 0 16 16"
              fill="currentColor"
              aria-hidden="true"
            >
              <path
                fillRule="evenodd"
                d="M8 15A7 7 0 108 1a7 7 0 000 14zM8 4a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 018 4zm0 8a1 1 0 100-2 1 1 0 000 2z"
                clipRule="evenodd"
              />
            </svg>
            <span>
              <strong>Error:</strong> {error}
            </span>
          </div>
        )}


        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="lookup-field">
            <span className="lookup-label">Username</span>
            <input
              className="lookup-input"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g. test_judge"
              autoComplete="username"
              required
            />
          </label>


          <label className="lookup-field">
            <span className="lookup-label">Password</span>
            <input
              className="lookup-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              required
            />
          </label>


          <button
            className="lookup-button auth-submit-btn"
            type="submit"
            disabled={loading}
          >
            {loading ? (
              <>
                <span className="button-spinner" aria-hidden="true" />
                Logging in…
              </>
            ) : (
              "Log in"
            )}
          </button>
        </form>


        <div className="auth-footer">
          <p>
            Don't have an account?{" "}
            <button
              type="button"
              className="auth-link-button"
              onClick={onSwitchToSignup}
            >
              Sign up
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
