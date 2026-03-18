/**
 * Time formatting utilities.
 *
 * All backend timestamps are UTC. These helpers convert to the user's
 * local system timezone for display — the backend stays in UTC.
 */

/**
 * Get the user's timezone abbreviation (e.g. "IST", "PST", "EST").
 */
export function getTimezoneLabel() {
  try {
    const parts = new Intl.DateTimeFormat(undefined, { timeZoneName: "short" }).formatToParts(new Date());
    const tz = parts.find((p) => p.type === "timeZoneName");
    return tz?.value || "Local";
  } catch {
    return "Local";
  }
}

/**
 * Format a UTC timestamp string to local HH:MM:SS (24-hour).
 *
 * @param {string} ts - ISO 8601 timestamp from the backend (UTC).
 * @returns {string} Formatted local time, e.g. "14:32:05".
 */
export function fmtLocalTime(ts) {
  if (!ts) return "\u2014";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "\u2014";
  return d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

/**
 * Format a UTC timestamp to local HH:MM (no seconds).
 */
export function fmtLocalTimeShort(ts) {
  if (!ts) return "\u2014";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "\u2014";
  return d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * Format a UTC timestamp to local date + time.
 */
export function fmtLocalDateTime(ts) {
  if (!ts) return "\u2014";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "\u2014";
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
