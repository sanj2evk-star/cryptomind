import { useState, useEffect, useCallback, useRef } from "react";

// Backend URL: auto-detect at runtime.
// localhost/127.0.0.1 → local dev server on port 8000
// Anything else (Render, etc.) → same origin (empty string)
function detectBase() {
  if (typeof window === "undefined") return "";
  const h = window.location.hostname;
  if (h === "localhost" || h === "127.0.0.1") return "http://localhost:8000";
  return ""; // same-origin: Render, production, etc.
}
export const BASE = detectBase();

const FETCH_TIMEOUT_MS = 8000;

// ---------------------------------------------------------------------------
// Token management
// ---------------------------------------------------------------------------

export function getToken() {
  return localStorage.getItem("token");
}

export function setToken(token) {
  localStorage.setItem("token", token);
}

export function clearToken() {
  localStorage.removeItem("token");
}

// ---------------------------------------------------------------------------
// Auth guard — prevents spurious logouts from transient 401s
//
// Only triggers logout after consecutive 401s from DIFFERENT endpoints,
// not a single polling failure during backend restart.
// ---------------------------------------------------------------------------

let _consecutive401 = 0;
const _401_THRESHOLD = 3;  // need 3 consecutive 401s before logout
let _401Timer = null;

function _record401() {
  _consecutive401 += 1;
  // Reset counter after 15s of no 401s (transient issue passed)
  if (_401Timer) clearTimeout(_401Timer);
  _401Timer = setTimeout(() => { _consecutive401 = 0; }, 15000);

  if (_consecutive401 >= _401_THRESHOLD) {
    _consecutive401 = 0;
    console.warn("[auth] Multiple consecutive 401s — session invalid, logging out");
    clearToken();
    window.dispatchEvent(new Event("auth:logout"));
    return true; // did logout
  }
  console.debug(`[auth] 401 received (${_consecutive401}/${_401_THRESHOLD}) — waiting for confirmation`);
  return false; // not yet
}

function _resetAuthGuard() {
  // A successful authenticated request → reset the 401 counter
  _consecutive401 = 0;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Login
// ---------------------------------------------------------------------------

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
    _resetAuthGuard();
    console.debug("[auth] Login successful");
    return true;
  } catch (err) {
    return classifyError(err);
  }
}

// ---------------------------------------------------------------------------
// useApi hook — fetch JSON from FastAPI backend with auth
//
// Returns { data, error, loading, retry }.
//   - loading: true only during FIRST fetch (not subsequent polls)
//   - error: null on success, descriptive string on failure
//   - data: parsed JSON on success, PRESERVED on transient failure
//   - retry(): manually re-fetch (for retry buttons)
// ---------------------------------------------------------------------------

export function useApi(path, refreshMs = 0) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const hadDataRef = useRef(false);  // tracks if we ever received data

  const retry = useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let retryPending = false;  // prevents stacking retry timers

    async function fetchData(isRetry = false) {
      const token = getToken();
      if (!token) {
        // No token at all — don't spam requests, just mark unauthorized
        if (!cancelled) {
          setError("unauthorized");
          setLoading(false);
        }
        return;
      }

      try {
        const headers = { "Authorization": `Bearer ${token}` };
        const res = await fetchWithTimeout(`${BASE}${path}`, { headers });

        if (res.status === 401) {
          // Don't immediately logout — let the auth guard decide
          const didLogout = _record401();
          if (!didLogout && !isRetry && !retryPending) {
            // Transient 401 (e.g., backend restart) — retry once after short delay
            retryPending = true;
            console.debug(`[useApi] 401 on ${path} — retrying in 2s`);
            setTimeout(() => {
              retryPending = false;
              if (!cancelled) fetchData(true);
            }, 2000);
            return;
          }
          if (!cancelled) setError("unauthorized");
          return;
        }

        if (!res.ok) throw new Error(`Server error (${res.status})`);

        const json = await res.json();
        if (!cancelled) {
          setData(json);
          setError(null);
          hadDataRef.current = true;
          _resetAuthGuard();  // successful auth request
        }
      } catch (err) {
        if (!cancelled) {
          const errMsg = classifyError(err);
          // Always set error for visibility, but data is preserved (not cleared)
          setError(errMsg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();

    let interval;
    if (refreshMs > 0) {
      interval = setInterval(() => fetchData(), refreshMs);
    }

    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [path, refreshMs, tick]);

  return { data, error, loading, retry };
}
