interface LoadingSpinnerProps {
  label?: string;
  size?: 'sm' | 'md';
}

export function LoadingSpinner({ label, size = 'md' }: LoadingSpinnerProps) {
  return (
    <div className={`loading-spinner loading-spinner--${size}`} role="status">
      <span className="loading-spinner__ring" aria-hidden="true" />
      {label && <span className="loading-spinner__label">{label}</span>}
    </div>
  );
}