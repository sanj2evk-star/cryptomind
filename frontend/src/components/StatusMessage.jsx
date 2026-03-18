/**
 * Unified status display for loading / error / empty states.
 * Prevents pages from getting stuck on a blank loading screen.
 */

export function Loading({ message = "Loading..." }) {
  return (
    <div className="status-box">
      <div className="spinner" />
      <p>{message}</p>
    </div>
  );
}

export function ErrorBox({ message, onRetry }) {
  const isBackendDown =
    message === "Backend unavailable" ||
    message?.includes("timeout") ||
    message?.includes("Cannot connect");

  return (
    <div className="status-box error-box">
      <p className="error-title">{isBackendDown ? "Backend Unavailable" : "Something went wrong"}</p>
      <p className="error-detail">
        {isBackendDown
          ? "Cannot reach the API server. Make sure the backend is running on port 8000."
          : message}
      </p>
      {onRetry && (
        <button className="retry-btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ icon = "~", title, message }) {
  return (
    <div className="status-box empty-box">
      <span className="empty-icon">{icon}</span>
      <p className="empty-title">{title || "No data"}</p>
      {message && <p className="empty-detail">{message}</p>}
    </div>
  );
}
