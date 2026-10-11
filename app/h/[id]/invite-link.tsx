"use client";

import { Check, Link2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/shell";

export function InviteLink({ path }: { path: string }) {
  const [copied, setCopied] = useState(false);
  const [url, setUrl] = useState(path);
  useEffect(() => setUrl(`${window.location.origin}${path}`), [path]);
  return (
    <div className="mt-4 flex items-center gap-3 rounded-2xl border border-dashed border-line-strong px-4 py-3">
      <p className="min-w-0 flex-1 truncate text-sm text-ink-2" title={url}>
        Send the others this link: <span className="text-ink">{url}</span>
      </p>
      <Button
        variant="secondary"
        type="button"
        onClick={async () => {
          await navigator.clipboard.writeText(url);
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        }}
      >
        {copied ? <Check aria-hidden className="size-4" /> : <Link2 aria-hidden className="size-4" />}
        <span aria-live="polite">{copied ? "Copied" : "Copy link"}</span>
      </Button>
    </div>
  );
}
