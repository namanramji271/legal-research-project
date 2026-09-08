export const API_BASE = "http://localhost:8000";

export async function authFetch(url, options = {}) {
  let token = null;
  try {
    const raw = localStorage.getItem("auth");
    if (raw) {
      const parsed = JSON.parse(raw);
      token = parsed.token || parsed.access_token;
    }
  } catch {
    // Ignore JSON parse errors
  }

  const headers = new Headers(options.headers || {});
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  return fetch(url, {
    ...options,
    headers,
  });
}
