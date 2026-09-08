import { useState } from "react";
import { API_BASE } from "../api";

const ROLES = [
  { value: "lawyer", label: "Lawyer" },
  { value: "judge", label: "Judge" },
  { value: "student", label: "Student" },
  { value: "public", label: "Public" },
];

export default function SignupPage({ onLogin, onSwitchToLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("lawyer");
  const [loading, setLoading] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [usernameError, setUsernameError] = useState("");
  const [generalError, setGeneralError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmed = username.trim();

    setUsernameError("");
    setPasswordError("");
    setGeneralError("");

    if (!trimmed) {
      setUsernameError("Please enter a username.");
      return;
    }
    if (!password) {
      setPasswordError("Please enter a password.");
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(`${API_BASE}/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: trimmed,
          password,
          role,
        }),
      });

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        if (Array.isArray(data?.detail)) {
          let matched = false;
          for (const item of data.detail) {
            const loc = item?.loc || [];
            const msg = item?.msg || item?.message || "Validation error";
            if (loc.includes("password")) {
              setPasswordError(msg);
              matched = true;
            } else if (loc.includes("username")) {
              setUsernameError(msg);
              matched = true;
            }
          }
          if (!matched) {
            setGeneralError(
              data.detail.map((e) => e.msg || e.message).join(", ")
            );
          }
        } else if (typeof data?.detail === "string") {
          const detail = data.detail;
          if (
            detail.toLowerCase().includes("password") ||
            detail.toLowerCase().includes("character")
          ) {
            setPasswordError(detail);
          } else if (detail.toLowerCase().includes("username")) {
            setUsernameError(detail);
          } else {
            setGeneralError(detail);
          }
        } else {
          setGeneralError("Signup failed. Please try again.");
        }
        return;
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
      setGeneralError(err.message || "Failed to create account.");
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
          <h1>Create an account</h1>
          <p className="auth-lead">
            Select your self-declared role to personalize your research workspace.
          </p>
        </div>

        {generalError && (
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
              <strong>Error:</strong> {generalError}
            </span>
          </div>
        )}

        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="lookup-field">
            <span className="lookup-label">Username</span>
            <input
              className={`lookup-input${usernameError ? " lookup-input-error" : ""}`}
              type="text"
              value={username}
              onChange={(e) => {
                setUsername(e.target.value);
                if (usernameError) setUsernameError("");
              }}
              placeholder="e.g. advocate_sharma"
              autoComplete="username"
              required
            />
            {usernameError && (
              <div className="auth-field-error-box" role="alert">
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
                  <strong>Error:</strong> {usernameError}
                </span>
              </div>
            )}
          </label>

          <label className="lookup-field">
            <span className="lookup-label">Password</span>
            <input
              className={`lookup-input${passwordError ? " lookup-input-error" : ""}`}
              type="password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                if (passwordError) setPasswordError("");
              }}
              placeholder="••••••••"
              autoComplete="new-password"
              required
            />
            {passwordError && (
              <div className="auth-field-error-box" role="alert">
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
                  <strong>Error:</strong> {passwordError}
                </span>
              </div>
            )}
          </label>

          <label className="lookup-field">
            <span className="lookup-label">Role</span>
            <select
              className="lookup-select"
              value={role}
              onChange={(e) => setRole(e.target.value)}
            >
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>

          <button
            className="lookup-button auth-submit-btn"
            type="submit"
            disabled={loading}
          >
            {loading ? (
              <>
                <span className="button-spinner" aria-hidden="true" />
                Creating account…
              </>
            ) : (
              "Sign up"
            )}
          </button>
        </form>

        <div className="auth-footer">
          <p>
            Already have an account?{" "}
            <button
              type="button"
              className="auth-link-button"
              onClick={onSwitchToLogin}
            >
              Log in
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
