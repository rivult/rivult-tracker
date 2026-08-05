/** Fixed left column: stat pages, divider, meta pages, sync control. */
import { RefreshCw } from "lucide-react";
import { cn } from "../lib/cn";
import { CLOUD_ENABLED } from "../lib/features";
import { useData } from "../state/DataContext";

export const STAT_PAGES = ["Today", "Games", "Breakdowns", "Trends", "Personal Bests", "Bridging"] as const;
// Snapshot sits BELOW the divider with the utility pages, not with the
// analysis pages above it. It is a lookup table rather than something to read
// and interpret, and the user asked for it "off to the side".
export const META_PAGES = ["Snapshot", "Account", "Settings", "Updates", "Community"] as const;

export type PageName = (typeof STAT_PAGES)[number] | (typeof META_PAGES)[number];

/** Meta pages actually offered in the nav. Account disappears while the cloud
 * backend is undeployed — the type keeps it so the code stays intact. */
export const VISIBLE_META_PAGES: readonly PageName[] = META_PAGES.filter(
  (p) => CLOUD_ENABLED || p !== "Account",
);

interface SidebarProps {
  active: PageName;
  onNavigate: (page: PageName) => void;
}

export function Sidebar({ active, onNavigate }: SidebarProps) {
  const { syncNow, syncing, lastSync, error } = useData();

  const syncLabel = lastSync
    ? lastSync.error
      ? lastSync.error
      : `${lastSync.log}: ${lastSync.synced} new game${lastSync.synced === 1 ? "" : "s"}` +
        (lastSync.in_progress ? " · one in progress" : "")
    : null;

  const item = (name: PageName) => (
    <button
      key={name}
      onClick={() => onNavigate(name)}
      className={cn(
        "rounded-md px-3 py-2 text-left text-sm transition-colors",
        active === name
          ? "bg-muted font-medium text-foreground"
          : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
      )}
    >
      {name}
    </button>
  );

  return (
    <aside className="flex w-52 shrink-0 flex-col overflow-y-auto border-r border-border bg-background py-4">
      <nav className="flex flex-col gap-1 px-2">
        {STAT_PAGES.map(item)}
        <div className="mx-2 my-3 h-px bg-border" />
        {VISIBLE_META_PAGES.map(item)}
      </nav>

      <div className="mt-auto px-4 pt-4 space-y-2">
        {error && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-2.5 py-2 text-xs text-danger">
            Backend unreachable — is the tracker running?
          </div>
        )}
        <button
          onClick={() => void syncNow()}
          disabled={syncing}
          className="flex w-full items-center justify-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground hover:bg-muted disabled:opacity-50"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", syncing && "animate-spin")} />
          {syncing ? "Reading log…" : "Sync log"}
        </button>
        {syncLabel && (
          <div className="text-[11px] leading-4 text-muted-foreground">{syncLabel}</div>
        )}
      </div>
    </aside>
  );
}
