export default function LoadingSpinner({ label }) {
  return (
    <div className="loading-panel" role="status" aria-live="polite">
      <div className="loading-spinner" aria-hidden="true" />
      {label ? <span className="loading-label">{label}</span> : null}
    </div>
  );
}

export function ResultSkeletonList({ count = 3 }) {
  return (
    <ul className="search-results skeleton-results" aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <li key={index} className="skeleton-card">
          <div className="skeleton-line skeleton-line-title" />
          <div className="skeleton-line skeleton-line-meta" />
          <div className="skeleton-line skeleton-line-body" />
          <div className="skeleton-line skeleton-line-body skeleton-line-short" />
        </li>
      ))}
    </ul>
  );
}
