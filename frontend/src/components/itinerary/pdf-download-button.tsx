import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import styles from "./pdf-download-button.module.css";

type PdfDownloadButtonProps = {
  onDownload: () => void;
  disabled?: boolean;
  isDownloading?: boolean;
  error?: string | null;
};

export function PdfDownloadButton({
  onDownload,
  disabled,
  isDownloading,
  error,
}: PdfDownloadButtonProps) {
  return (
    <div className={styles.wrapper}>
      <Button variant="secondary" onClick={onDownload} disabled={disabled || isDownloading}>
        {isDownloading ? <Spinner label="Downloading PDF" /> : <Download size={16} aria-hidden="true" />}
        {isDownloading ? "Preparing PDF…" : "Download PDF"}
      </Button>
      {error ? (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
