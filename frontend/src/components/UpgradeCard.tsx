/** Subscription entry point (design P2).
 *
 * Checkout and billing management both happen on Stripe-hosted pages: we ask
 * the local server, it asks the Worker, the Worker mints a URL, and we open
 * it in the system browser. No card details ever touch this app, which is
 * also why there is no payment form here to get wrong.
 *
 * Shown when the license is not active; subscribers get the manage-billing
 * row instead.
 */
import { useState } from "react";
import { ExternalLink, Sparkles } from "lucide-react";
import { api } from "../api/client";
import type { BillingUrl } from "../api/types";
import { Card, CardLabel } from "../components/shared";

const PLANS = [
  { id: "monthly", label: "Monthly", price: "$3.99", per: "/month", note: "" },
  { id: "annual", label: "Annual", price: "$30", per: "/year", note: "2 months free" },
] as const;

const PERKS = [
  "Breakdowns — every stat split by map, teammate, time of day and your tags",
  "Trends — week-by-week form as far back as your logs reach",
  "Full game history (free keeps the last 90 days)",
  "Cloud sync across devices",
];

function messageFor(r: BillingUrl | { error: string; code?: string }): string {
  if (r.code === "NETWORK") return "Can't reach Rivult — check your connection and try again.";
  if (r.code === "UNAUTHENTICATED") return "Sign in first, then subscribe.";
  if (r.code === "NO_CUSTOMER") return "No billing profile yet — subscribe first.";
  return r.error ?? "Something went wrong.";
}

/** Opens Stripe in the system browser and reports failures inline. */
function useBillingAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (key: string, call: () => Promise<BillingUrl>) => {
    setBusy(key);
    setError(null);
    try {
      const r = await call();
      if (r.url) window.open(r.url, "_blank", "noopener,noreferrer");
      else setError(messageFor(r));
    } catch (e) {
      setError(messageFor({ error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setBusy(null);
    }
  };

  return { busy, error, run };
}

export function UpgradeCard() {
  const { busy, error, run } = useBillingAction();

  return (
    <Card className="space-y-4 p-6">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-warn" />
        <CardLabel>Rivult Premium</CardLabel>
      </div>

      <ul className="space-y-1.5">
        {PERKS.map((p) => (
          <li key={p} className="flex gap-2.5 text-sm text-muted-foreground">
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-success/70" />
            {p}
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap gap-3">
        {PLANS.map((plan) => (
          <button
            key={plan.id}
            onClick={() => void run(plan.id, () => api.cloudCheckout(plan.id))}
            disabled={busy !== null}
            className="flex min-w-40 flex-col items-start gap-0.5 rounded-md border border-border bg-card px-4 py-3 text-left transition-colors hover:border-muted-foreground/50 disabled:opacity-50"
          >
            <span className="text-sm font-medium">
              {busy === plan.id ? "Opening Stripe…" : plan.label}
            </span>
            <span className="text-lg font-semibold">
              {plan.price}
              <span className="text-sm font-normal text-muted-foreground">{plan.per}</span>
            </span>
            {plan.note && <span className="text-xs text-success">{plan.note}</span>}
          </button>
        ))}
      </div>

      {error && <div className="text-sm text-danger">{error}</div>}
      <p className="text-xs text-muted-foreground">
        Checkout opens in your browser on Stripe&apos;s secure page. Cancel any time.
      </p>
    </Card>
  );
}

/** For existing subscribers: Stripe's own portal handles plan changes,
 * payment methods, invoices and cancellation, so we don't rebuild any of it. */
export function ManageBillingRow() {
  const { busy, error, run } = useBillingAction();
  return (
    <div className="space-y-1">
      <button
        onClick={() => void run("portal", () => api.cloudPortal())}
        disabled={busy !== null}
        className="flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
      >
        <ExternalLink className="h-3.5 w-3.5" />
        {busy ? "Opening…" : "Manage billing"}
      </button>
      {error && <div className="text-sm text-danger">{error}</div>}
    </div>
  );
}
