import styles from "./error-banner.module.css";

export function ErrorBanner({ message }: { message: string }) {
  return (
    <p role="alert" className={styles.banner}>
      {message}
    </p>
  );
}
