/** Premium gates. Free tier keeps Today (the peek: 7-day graph + per-tag
 * numbers) and the last 3 months of Games; Breakdowns and Trends are
 * premium. The license comes from the Rivult cloud (Account page) with an
 * offline grace window, so being briefly offline never locks a subscriber out.
 */
import { Lock } from "lucide-react";
import { Card } from "./shared";

export function LockedPage({
  title,
  blurb,
  onGoToAccount,
}: {
  title: string;
  blurb: string;
  onGoToAccount: () => void;
}) {
  return (
    <div className="space-y-6 pb-24">
      <h1 className="text-3xl font-bold">{title}</h1>
      <Card className="flex flex-col items-center gap-4 p-12 text-center">
        <div className="rounded-full bg-muted p-4">
          <Lock className="h-8 w-8 text-muted-foreground" />
        </div>
        <div className="max-w-md space-y-2">
          <div className="text-lg font-semibold">{title} is a premium view</div>
          <p className="text-sm text-muted-foreground">{blurb}</p>
          <p className="text-sm text-muted-foreground">
            Your free peek lives on the Today page — the 7-day graph and per-tag numbers.
          </p>
        </div>
        <button
          onClick={onGoToAccount}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/80"
        >
          Upgrade on the Account page
        </button>
      </Card>
    </div>
  );
}

export function HistoryClampBanner({ onGoToAccount }: { onGoToAccount?: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/30 px-4 py-2.5 text-sm">
      <span className="flex items-center gap-2 text-muted-foreground">
        <Lock className="h-3.5 w-3.5" />
        Free plan shows the last 3 months of games.
      </span>
      {onGoToAccount ? (
        <button
          onClick={onGoToAccount}
          className="shrink-0 text-foreground underline-offset-2 hover:underline"
        >
          Unlock full history
        </button>
      ) : (
        <span className="shrink-0 text-muted-foreground">Upgrade on the Account page.</span>
      )}
    </div>
  );
}
