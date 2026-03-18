import { useState, useEffect, useCallback } from "react";

// Single source of truth for the backend URL.
// On Render (or any deployment where frontend is served by the backend),
// use "" (same origin). Only use localhost for local development.
const _isLocalhost = typeof window !== "undefined" && window.location.hostname === "localhost";
export const BASE = (
  import.meta.env.VITE_API_URL ||
  (_isLocalhost ? "http://localhost:8000" : "")
).replace(/\/$/, "");

const FETCH_TIMEOUT_MS = 8000;

export function getToken() {
  return localStorage.getItem("token");
}

export function setToken(token) {
  localStorage.setItem("token", token);
}

export function clearToken() {
  localStorage.removeItem("token");
}

async function fetchWithTimeout(url, options, timeoutMs = FETCH_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function classifyError(err) {
  if (err.name === "AbortError") return "Request timed out";
  const msg = err.message || "";
  if (msg.includes("Failed to fetch") || msg.includes("NetworkError") || msg.includes("CORS"))
    return "Backend unavailable";
  return msg || "Unknown error";
}

/**
 * Login and store the token.
 * Returns: true on success, error string on failure.
 */
export async function login(username, password) {
  try {
    const res = await fetchWithTimeout(`${BASE}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (res.status === 401) return "Invalid username or password";
    if (!res.ok) return `Server error (${res.status})`;
    const data = await res.json();
    setToken(data.access_token);
    return true;
  } catch (err) {
    return classifyError(err);
  }
}

/**
 * Fetch JSON from the FastAPI backend with auth.
 *
 * Returns { data, error, loading, retry }.
 *   - loading: true while first fetch is in progress
 *   - error: null on success, descriptive string on failure
 *   - data: parsed JSON on success, null on failure
 *   - retry(): manually re-fetch (for retry buttons)
 */
export function useApi(path, refreshMs = 0) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  const retry = useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      const token = getToken();
      try {
        const headers = {};
        if (token) headers["Authorization"] = `Bearer ${token}`;

        const res = await fetchWithTimeout(`${BASE}${path}`, { headers });

        if (res.status === 401) {
          clearToken();
          if (!cancelled) setError("unauthorized");
          window.dispatchEvent(new Event("auth:logout"));
          return;
        }
        if (!res.ok) throw new Error(`Server error (${res.status})`);

        const json = await res.json();
        if (!cancelled) {
          setData(json);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(classifyError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();

    let interval;
    if (refreshMs > 0) {
      interval = setInterval(fetchData, refreshMs);
    }

    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [path, refreshMs, tick]);

  return { data, error, loading, retry };
}
