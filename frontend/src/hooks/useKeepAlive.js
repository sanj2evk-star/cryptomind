import { useEffect, useRef, useState, useCallback } from "react";

function _detectApi() {
  if (typeof window === "undefined") return "";
  const h = window.location.hostname;
  if (h === "localhost" || h === "127.0.0.1") return "http://localhost:8000";
  return "";
}
const API = _detectApi();

const PING_INTERVAL_MS = 4 * 60 * 1000; // 4 minutes

/**
 * Keep-alive hook for Render free tier.
 * Pings /ping every 4 min while page is visible.
 * Returns { status, lastPing, consecutiveFailures }
 *   status: "LIVE" | "CONNECTING" | "SLEEPING" | "ERROR"
 */
export function useKeepAlive() {
  const [status, setStatus] = useState("CONNECTING");
  const [lastPing, setLastPing] = useState(null);
  const failRef = useRef(0);
  const intervalRef = useRef(null);

  const ping = useCallback(async () => {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 6000);
      const res = await fetch(`${API}/ping`, { signal: controller.signal });
      clearTimeout(timer);
      if (res.ok) {
        failRef.current = 0;
        setStatus("LIVE");
        setLastPing(new Date());
        return;
      }
    } catch (_) { /* ignore */ }

    failRef.current += 1;
    if (failRef.current >= 3) {
      setStatus("ERROR");
    } else if (failRef.current >= 1) {
      setStatus("SLEEPING");
    }
  }, []);

  useEffect(() => {
    // Initial ping
    ping();

    // Start interval
    intervalRef.current = setInterval(ping, PING_INTERVAL_MS);

    // Pause when hidden, resume when visible
    const onVisibility = () => {
      if (document.hidden) {
        if (intervalRef.current) clearInterval(intervalRef.current);
      } else {
        ping(); // immediate ping on return
        intervalRef.current = setInterval(ping, PING_INTERVAL_MS);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [ping]);

  return { status, lastPing, consecutiveFailures: failRef.current };
}
