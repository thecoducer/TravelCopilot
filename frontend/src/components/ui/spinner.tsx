export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span
      role="status"
      aria-label={label}
      className="inline-block size-4 animate-spin rounded-full border-2 border-border-strong border-t-accent"
    />
  );
}
