import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

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
    <div className="flex flex-col items-end gap-1">
      <Button
        variant="secondary"
        className="shrink-0 whitespace-nowrap"
        onClick={onDownload}
        disabled={disabled || isDownloading}
      >
        {isDownloading ? <Spinner label="Downloading PDF" /> : <Download size={16} aria-hidden="true" />}
        {isDownloading ? "Preparing PDF…" : "Download PDF"}
      </Button>
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
