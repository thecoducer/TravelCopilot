export function ErrorBanner({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="rounded-md border border-danger/40 bg-danger-soft px-4 py-3 text-sm text-danger"
    >
      {message}
    </p>
  );
}
