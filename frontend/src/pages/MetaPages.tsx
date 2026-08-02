/** Account (Rivult cloud sync), Updates (version/changelog), Community.
 * The Account page drives the SaaS layer (bedwars-cloud) through the local
 * server's /api/cloud/* proxy — the browser never holds the token.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Clock, Cloud, CloudOff, LogOut, RefreshCw, Share2, User, Users } from "lucide-react";
import { api } from "../api/client";
import type { CloudDevices, CloudStatus, CloudSyncResult, VersionInfo } from "../api/types";
import { DeleteAccountCard } from "../components/DeleteAccountCard";
import { FeedbackCard } from "../components/FeedbackCard";
import { ShareCardModal } from "../components/ShareCardModal";
import { ManageBillingRow, UpgradeCard } from "../components/UpgradeCard";
import { Card, CardLabel } from "../components/shared";
import { cn } from "../lib/cn";

export { SettingsPage } from "./SettingsPage";

function PageHeader({ icon, title, desc }: { icon: ReactNode; title: string; desc: string }) {
  return (
    <div className="flex items-center gap-4 border-b border-border pb-6">
      <div className="rounded-lg bg-muted p-3">{icon}</div>
      <div>
        <h1 className="text-3xl font-bold">{title}</h1>
        <p className="mt-1 text-muted-foreground">{desc}</p>
      </div>
    </div>
  );
}

const inputCls =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus:border-muted-foreground/60";

// -- Account ----------------------------------------------------------------

export function AccountPage() {
  const [status, setStatus] = useState<CloudStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((refresh: boolean) => {
    api
      .cloudStatus(refresh)
      .then((s) => {
        setStatus(s);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    load(true);
  }, [load]);

  return (
    <div className="space-y-6 pb-24">
      <PageHeader
        icon={<User className="h-8 w-8" />}
        title="Account"
        desc="Cloud sync and identity — local-first, the cloud is a mirror."
      />
      {error && <div className="text-sm text-danger">Local server error: {error}</div>}
      {!status && !error && <div className="text-sm text-muted-foreground">Loading…</div>}
      {status &&
        (status.logged_in ? (
          <LoggedIn status={status} reload={() => load(true)} />
        ) : (
          <LoggedOut onDone={() => load(true)} />
        ))}
    </div>
  );
}

function LoggedOut({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<"login" | "register" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (kind: "login" | "register") => {
    setBusy(kind);
    setErr(null);
    try {
      const r = await (kind === "login"
        ? api.cloudLogin(email.trim(), password)
        : api.cloudRegister(email.trim(), password));
      if (r.error) {
        setErr(r.code === "NETWORK" ? "Can't reach the Rivult cloud — are you online?" : r.error);
      } else {
        onDone();
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Card className="space-y-4 p-6">
        <CardLabel>Sign in to Rivult</CardLabel>
        <input
          className={inputCls}
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="email"
        />
        <input
          className={inputCls}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void submit("login")}
          placeholder="password"
        />
        <div className="flex items-center gap-2">
          <button
            onClick={() => void submit("login")}
            disabled={busy !== null || !email.trim() || !password}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/80 disabled:opacity-50"
          >
            {busy === "login" ? "Signing in…" : "Sign in"}
          </button>
          <button
            onClick={() => void submit("register")}
            disabled={busy !== null || !email.trim() || !password}
            className="rounded-md border border-border bg-card px-4 py-2 text-sm hover:bg-muted disabled:opacity-50"
          >
            {busy === "register" ? "Creating…" : "Create account"}
          </button>
        </div>
        {err && <div className="text-sm text-danger">{err}</div>}
      </Card>
      <Card className="space-y-3 p-6">
        <CardLabel>Why sign in?</CardLabel>
        <p className="text-sm text-muted-foreground">
          Your games live in a local database and every page works without an account. Signing in
          adds cloud sync: games and tags mirror across your devices, and tagging on one machine
          shows up on the others.
        </p>
        <p className="text-sm text-muted-foreground">
          Free tier available — nothing here is paywalled today.
        </p>
      </Card>
    </div>
  );
}

function LoggedIn({ status, reload }: { status: CloudStatus; reload: () => void }) {
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<CloudSyncResult | null>(null);
  const [devices, setDevices] = useState<CloudDevices | null>(null);

  const loadDevices = useCallback(() => {
    api.cloudDevices().then(setDevices).catch(() => setDevices(null));
  }, []);

  useEffect(loadDevices, [loadDevices]);

  const lic = status.license;
  const licenseLabel =
    lic.status === "active"
      ? `Premium${lic.plan ? ` · ${lic.plan}` : ""}`
      : lic.graceExpired
        ? "Free (premium check overdue — go online)"
        : lic.status === "expired"
          ? "Expired"
          : "Free";

  const sync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const r = await api.cloudSync();
      setSyncResult(r);
      reload();
    } catch (e) {
      setSyncResult({ error: String(e), code: "LOCAL" });
    } finally {
      setSyncing(false);
    }
  };

  const totals = (t?: { games: number; tags: number; game_tags: number }) =>
    t ? `${t.games} games, ${t.tags} tags, ${t.game_tags} tag links` : "—";

  return (
    <div className="space-y-6">
      <div className="grid gap-6 md:grid-cols-2">
        <Card className="space-y-3 p-6">
          <CardLabel>Signed in</CardLabel>
          <div className="text-lg font-medium">{status.email}</div>
          <div className="flex items-center gap-2 text-sm">
            <span
              className={cn(
                "rounded px-2 py-0.5 text-xs font-medium",
                lic.status === "active" ? "bg-success/15 text-success" : "bg-muted text-muted-foreground",
              )}
            >
              {licenseLabel}
            </span>
            {lic.periodEnd && (
              <span className="text-muted-foreground">renews {lic.periodEnd.slice(0, 10)}</span>
            )}
          </div>
          {lic.status === "active" && <ManageBillingRow />}
          <button
            onClick={() => void api.cloudLogout().then(reload)}
            className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <LogOut className="h-3.5 w-3.5" /> Sign out
          </button>
        </Card>

        <Card className="space-y-3 p-6">
          <CardLabel>Cloud sync</CardLabel>
          <div className="text-sm text-muted-foreground">
            {status.last_sync
              ? `Last synced ${status.last_sync.slice(0, 16).replace("T", " ")} UTC`
              : "Never synced from this device."}
          </div>
          <button
            onClick={() => void sync()}
            disabled={syncing}
            className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/80 disabled:opacity-50"
          >
            {syncing ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Cloud className="h-4 w-4" />}
            {syncing ? "Syncing…" : "Sync now"}
          </button>
          {syncResult &&
            (syncResult.error ? (
              <div className="flex items-center gap-1.5 text-sm text-danger">
                <CloudOff className="h-4 w-4" />
                {syncResult.code === "NETWORK" ? "Offline — will catch up next time." : syncResult.error}
              </div>
            ) : (
              <div className="text-sm text-success">
                Pushed {totals(syncResult.pushed)} · pulled {totals(syncResult.pulled)}
              </div>
            ))}
        </Card>
      </div>

      {lic.status !== "active" && <UpgradeCard />}

      <Card className="p-6">
        <div className="mb-3 flex items-baseline justify-between">
          <CardLabel>Devices</CardLabel>
          {devices?.limit != null && (
            <span className="text-xs text-muted-foreground">
              {devices.activeCount}/{devices.limit} active
            </span>
          )}
        </div>
        {devices?.error && (
          <div className="text-sm text-muted-foreground">
            {devices.code === "NETWORK" ? "Offline — device list unavailable." : devices.error}
          </div>
        )}
        {devices?.devices?.map((d) => (
          <div
            key={d.id}
            className="flex items-center justify-between border-b border-border/60 py-2.5 text-sm last:border-0"
          >
            <div>
              <span className="font-medium">{d.name || d.device_id.slice(0, 8)}</span>
              <span className="ml-2 text-muted-foreground">{d.platform ?? ""}</span>
            </div>
            <div className="flex items-center gap-3">
              {d.last_seen_at && (
                <span className="text-xs text-muted-foreground">
                  seen {new Date(d.last_seen_at * 1000).toLocaleDateString()}
                </span>
              )}
              <button
                onClick={() => void api.cloudRevokeDevice(d.id).then(loadDevices)}
                className="text-xs text-muted-foreground hover:text-danger"
              >
                revoke
              </button>
            </div>
          </div>
        ))}
        {devices && !devices.error && !devices.devices?.length && (
          <div className="text-sm text-muted-foreground">No active devices.</div>
        )}
      </Card>

      <DeleteAccountCard email={status.email ?? ""} onDeleted={reload} />
    </div>
  );
}

// -- Updates ----------------------------------------------------------------

/** This release, in full. Kept to a handful of lines — a wall of paragraphs is
 * one nobody reads. Anything that needs the user to DO something says so. */
const LATEST = [
  "Settings save themselves — no more Save button.",
  "Six new Breakdowns: how you die, diamond economy, kill participation, streak state, day & time, early economy.",
  "Upgrades now lists every upgrade (Haste, forges, traps), and items tracks 18 categories instead of 7 — fireball and gapples were missing entirely.",
  "Games page: one search box that finds any player, opponents included. Alt-account games are hidden instead of greyed.",
  "Unresolved games can be marked a win or a loss, or removed — and your answer survives a log refresh.",
  "Trends: baseline numbers up top, a window slider, and a second line for only the sessions you tag.",
  "Keybind changes apply straight away. Before this they silently did nothing until you restarted the app.",
  "Alt accounts are detected again. Tick yours on in Settings → Accounts, then run Settings → Maintenance → Full log refresh.",
  "Auto commands actually type now — they never worked before. Settings shows what the last attempt did.",
  "The keybind popup no longer beeps, and is now a rounded pill you can move to any corner (Settings → Show me to preview it).",
  "Search any player in the Games filter bar, opponents included, not just teammates.",
  "Set a tagging keybind by pressing the key instead of picking it from a list.",
];

/** Older releases, one line each. */
const OLDER = [
  "Rotated-log games are dated by when you played them",
  "Games grouped by day instead of by session",
  "Trends plots a rolling average over your last N games",
  "Exact date ranges, and Breakdowns opens on the last 30 days",
  "Losses are detected on alts; only ticked accounts count",
  "Keybind toast slides down in the tag's colour, over fullscreen",
  "Default binds are Ctrl+Alt+F6–F9, so Medal keeps its key",
  "Custom tag colours",
  "Window sizes itself to your monitor; wide screens use the space",
  "One-click updates from the Updates page",
  "Closing the window minimises to the system tray and keeps tracking",
  "Tagging keybinds — mark a game mid-fight without alt-tabbing",
  "Bridging analyzer isolates real speed-bridging",
  "Optional auto /locraw + /who restores map and mode detection",
  "Dream modes detected from chat and kept out of every stat",
  "Enemy-wipe wins resolve even when the log cuts off",
  "Item tracking (potions, pearls, KB stick, bow, gear) in Breakdowns",
  "One-click full log refresh in Settings → Maintenance",
  "Fixed 'summoned' and 'server' being logged as teammates",
  "New dashboard: Today, Games, Breakdowns, Trends, Personal Bests",
  "Instant tagging, with Ctrl+click to tag a whole session",
  "Games from days the app was closed import automatically",
  "Tag filtering everywhere: All / Untagged / Tagged, include and exclude",
  "Accurate modes and maps, replay exclusion, rename-proof identity",
];

export function UpdatesPage() {
  const [version, setVersion] = useState<VersionInfo | null>(null);
  const [installing, setInstalling] = useState(false);
  const [installMsg, setInstallMsg] = useState<string | null>(null);

  useEffect(() => {
    api.version().then(setVersion).catch(() => setVersion(null));
  }, []);

  const install = async () => {
    setInstalling(true);
    setInstallMsg(null);
    try {
      const r = await api.installUpdate();
      if (r.installing) {
        setInstallMsg("Downloading the update — Rivult will restart in a moment.");
      } else {
        // a refusal (up_to_date, in_game, not_frozen, download_failed…)
        setInstallMsg(r.message ?? "Couldn't install the update.");
        setInstalling(false);
      }
    } catch (e) {
      setInstallMsg(e instanceof Error ? e.message : String(e));
      setInstalling(false);
    }
  };

  return (
    <div className="space-y-6 pb-24">
      <PageHeader icon={<Clock className="h-8 w-8" />} title="Updates" desc="Changelog and version." />
      {version?.update_available && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-success/50 bg-success/10 px-4 py-3 text-sm">
          <span>
            Update available: v{version.latest} (you have v{version.current}).
          </span>
          <button
            onClick={() => void install()}
            disabled={installing}
            className="rounded-md bg-success/90 px-3 py-1.5 text-xs font-medium text-background transition-colors hover:bg-success disabled:opacity-60"
          >
            {installing ? "Installing…" : "Install & restart"}
          </button>
        </div>
      )}
      {installMsg && <div className="text-sm text-muted-foreground">{installMsg}</div>}
      <Card className="p-6">
        <CardLabel>Current version</CardLabel>
        <div className="mt-2 text-4xl font-bold tabular-nums">
          {version ? `v${version.current}` : "—"}
        </div>
        {version?.error && (
          <div className="mt-2 text-xs text-muted-foreground">
            Update check: {version.error}
          </div>
        )}
      </Card>

      <FeedbackCard version={version?.current} />
      <WhatsNewCard />
    </div>
  );
}

/** This release expanded, everything before it one click away. */
function WhatsNewCard() {
  const [showOlder, setShowOlder] = useState(false);
  return (
    <Card className="p-6">
      <CardLabel>What&apos;s new</CardLabel>
      <ul className="mt-3 space-y-2">
        {LATEST.map((line) => (
          <li key={line} className="flex gap-2.5 text-sm">
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-success/70" />
            {line}
          </li>
        ))}
      </ul>
      <button
        onClick={() => setShowOlder((v) => !v)}
        className="mt-4 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
      >
        {showOlder ? "Hide earlier changes" : `Earlier changes (${OLDER.length})`}
      </button>
      {showOlder && (
        <ul className="mt-3 space-y-1 border-t border-border/60 pt-3">
          {OLDER.map((line) => (
            <li key={line} className="flex gap-2.5 text-xs text-muted-foreground">
              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50" />
              {line}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// -- Community --------------------------------------------------------------

export function CommunityPage() {
  const [sharing, setSharing] = useState(false);
  return (
    <div className="space-y-6 pb-24">
      <PageHeader
        icon={<Users className="h-8 w-8" />}
        title="Community"
        desc="Feedback in, share cards out."
      />
      <Card className="space-y-3 p-6">
        <CardLabel>Feedback</CardLabel>
        <div className="flex gap-2">
          <button disabled className="rounded-md border border-border bg-card px-4 py-2 text-sm opacity-50">
            Join the Discord
          </button>
          <button disabled className="rounded-md border border-border bg-card px-4 py-2 text-sm opacity-50">
            Send feedback
          </button>
        </div>
        <div className="text-xs text-muted-foreground">Links land here at launch.</div>
      </Card>
      <Card className="space-y-3 p-6">
        <CardLabel>Share cards</CardLabel>
        <p className="text-sm text-muted-foreground">
          Export a clean stat card of your recent form to post in the Rivult Discord or drop in a
          clip description — the tool and the content feed each other.
        </p>
        <button
          onClick={() => setSharing(true)}
          className="flex w-fit items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/80"
        >
          <Share2 className="h-4 w-4" /> Create a 7-day card
        </button>
      </Card>
      {sharing && <ShareCardModal scope="7d" onClose={() => setSharing(false)} />}
    </div>
  );
}
