/**
 * useTradeSound — Audio feedback for trading events.
 *
 * Uses Web Audio API to generate short tones. No audio files needed.
 * Sounds:
 *   - trade placed: soft click (neutral)
 *   - trade won: ascending chime (positive)
 *   - trade lost: descending tone (subtle negative)
 *
 * Features:
 *   - mute/unmute toggle (persisted in localStorage)
 *   - duplicate protection (tracks last trade ID)
 *   - browser autoplay unlock on first interaction
 *   - debounce (min 2s between sounds)
 */

import { useState, useRef, useCallback, useEffect } from "react";

const STORAGE_KEY = "cryptomind_sound_enabled";

// Get or create AudioContext (shared singleton)
let _ctx = null;
function getCtx() {
  if (!_ctx) {
    _ctx = new (window.AudioContext || window.webkitAudioContext)();
  }
  // Resume if suspended (browser autoplay policy)
  if (_ctx.state === "suspended") {
    _ctx.resume().catch(() => {});
  }
  return _ctx;
}

// ── Sound generators ──

function playTradePlaced() {
  try {
    const ctx = getCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = "sine";
    osc.frequency.setValueAtTime(800, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(600, ctx.currentTime + 0.15);
    gain.gain.setValueAtTime(0.12, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.2);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.2);
  } catch (_) {}
}

function playTradeWon() {
  try {
    const ctx = getCtx();
    const t = ctx.currentTime;

    // Two ascending tones
    [0, 0.12].forEach((delay, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = "sine";
      const freq = i === 0 ? 523 : 659; // C5 → E5
      osc.frequency.setValueAtTime(freq, t + delay);
      gain.gain.setValueAtTime(0.1, t + delay);
      gain.gain.exponentialRampToValueAtTime(0.001, t + delay + 0.25);
      osc.start(t + delay);
      osc.stop(t + delay + 0.25);
    });
  } catch (_) {}
}

function playTradeLost() {
  try {
    const ctx = getCtx();
    const t = ctx.currentTime;

    // Single descending tone
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = "triangle";
    osc.frequency.setValueAtTime(440, t);
    osc.frequency.exponentialRampToValueAtTime(300, t + 0.4);
    gain.gain.setValueAtTime(0.08, t);
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.4);
    osc.start(t);
    osc.stop(t + 0.4);
  } catch (_) {}
}

// ── Hook ──

export function useTradeSound() {
  const [enabled, setEnabled] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) !== "false"; }
    catch { return true; }
  });

  const lastTradeRef = useRef(null);     // last trade timestamp to prevent duplicates
  const lastSoundRef = useRef(0);        // debounce: last sound time

  const toggle = useCallback(() => {
    setEnabled(prev => {
      const next = !prev;
      try { localStorage.setItem(STORAGE_KEY, String(next)); } catch {}
      // Unlock audio context on user interaction
      if (next) getCtx();
      return next;
    });
  }, []);

  // Unlock audio on first click anywhere
  useEffect(() => {
    const unlock = () => { if (enabled) getCtx(); };
    document.addEventListener("click", unlock, { once: true });
    document.addEventListener("touchstart", unlock, { once: true });
    return () => {
      document.removeEventListener("click", unlock);
      document.removeEventListener("touchstart", unlock);
    };
  }, [enabled]);

  /**
   * Check trades and play appropriate sound.
   * Call this with the latest trades array from the API.
   * @param {Array} trades - recent trades from /auto/trades
   */
  const checkTrades = useCallback((trades) => {
    if (!enabled || !trades || trades.length === 0) return;

    const latest = trades[0]; // newest trade (already sorted newest-first)
    if (!latest || !latest.timestamp) return;

    // Duplicate check — same trade timestamp
    if (latest.timestamp === lastTradeRef.current) return;

    // Debounce — min 2s between sounds
    const now = Date.now();
    if (now - lastSoundRef.current < 2000) return;

    const action = (latest.action || "").toUpperCase();
    if (action === "HOLD") return; // don't sound on holds

    lastTradeRef.current = latest.timestamp;
    lastSoundRef.current = now;

    const pnl = parseFloat(latest.pnl) || 0;

    if (action === "BUY" || (action === "SELL" && pnl === 0)) {
      // Trade placed (BUY, or SELL with no P&L data yet)
      playTradePlaced();
    } else if (action === "SELL" && pnl > 0) {
      // Trade won
      playTradeWon();
    } else if (action === "SELL" && pnl < 0) {
      // Trade lost
      playTradeLost();
    }
  }, [enabled]);

  return { enabled, toggle, checkTrades };
}
