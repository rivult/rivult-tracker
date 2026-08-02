/** "Tell me what's broken" — the feedback contact for the closed beta.
 *
 * Shows the address as copyable text rather than relying on a mailto: link:
 * the app runs inside a pywebview/WebView2 shell where mailto often does
 * nothing at all, and a dead link looks worse than no link. The mailto is
 * offered as a convenience, with copy as the reliable path.
 */
import { useState } from "react";
import { Check, Copy, Mail } from "lucide-react";
import { Card, CardLabel } from "../components/shared";

export const CONTACT_EMAIL = "contact@rivult.net";

export function FeedbackCard({ version }: { version?: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(CONTACT_EMAIL);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false); // clipboard blocked — the address is selectable anyway
    }
  };

  const subject = encodeURIComponent(`Rivult feedback${version ? ` (v${version})` : ""}`);

  return (
    <Card className="space-y-3 p-6">
      <div className="flex items-center gap-2">
        <Mail className="h-4 w-4 text-muted-foreground" />
        <CardLabel>Feedback</CardLabel>
      </div>
      <p className="text-sm text-muted-foreground">
        This is an early build and I genuinely want to hear what&apos;s wrong with it — wrong
        numbers, confusing screens, anything that crashed. Bug reports are more useful than
        compliments.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <code className="select-all rounded-md border border-border bg-background px-3 py-1.5 text-sm">
          {CONTACT_EMAIL}
        </code>
        <button
          onClick={() => void copy()}
          className="flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-xs hover:bg-muted"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
        <a
          href={`mailto:${CONTACT_EMAIL}?subject=${subject}`}
          className="rounded-md border border-border bg-card px-3 py-1.5 text-xs hover:bg-muted"
        >
          Open mail app
        </a>
      </div>
      <p className="text-xs text-muted-foreground">
        If something crashed or behaved oddly, attach <code>rivult.log</code> from the folder the
        app runs in — it holds the error and saves a lot of guesswork.
      </p>
    </Card>
  );
}
