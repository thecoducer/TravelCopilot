import styles from "./spinner.module.css";

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <span className={styles.spinner} role="status" aria-label={label} />;
}
