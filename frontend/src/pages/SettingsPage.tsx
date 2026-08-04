/** Settings — app prefs + tag management (create/delete/rename), per the
 * handoff, plus maintenance (full log refresh) and auto-commands.
 */
import { useEffect, useRef, useState } from "react";
import { Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { AccountInfo, KeybindMap, RefreshAllResult, Settings } from "../api/types";
import { KeybindConfig } from "../components/KeybindConfig";
import { Card, CardLabel } from "../components/shared";
import { TagColorPicker } from "../components/TagColorPicker";
import { CHAT_KEY_OPTIONS, DEFAULT_CHAT_KEY } from "../lib/chatKeys";
import { cn } from "../lib/cn";
import { tagColor } from "../lib/format";
import { DEFAULT_TREND_WINDOW, TREND_WINDOWS } from "../lib/trends";
import { useData } from "../state/DataContext";

const inputCls =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus:border-muted-foreground/60";

interface SettingsValues {
  player: string;
  logPath: string;
  updateUrl: string;
  autoCmdEnabled: boolean;
  autoCmdDelay: number;
  chatKey: string;
  keybindMap: KeybindMap;
  keybindOverlay: boolean;
  overlayPlacement: string;
  trayEnabled: boolean;
  countedAccounts: string[];
  trendWindow: number;
}

/** The POST body, built in ONE place.
 *
 * Autosave compares `JSON.stringify` of this against the last saved copy, so
 * both the baseline (built when settings load) and the live value must come
 * from the same function — key order is part of the comparison. */
function settingsPayload(v: SettingsValues) {
  return {
    player: v.player,
    log_path: v.logPath,
    update_url: v.updateUrl,
    autocmd_enabled: v.autoCmdEnabled,
    autocmd_delay_s: v.autoCmdDelay,
    autocmd_chat_key: v.chatKey,
    keybind_map: v.keybindMap,
    keybind_overlay: v.keybindOverlay,
    overlay_placement: { preset: v.overlayPlacement },
    tray_enabled: v.trayEnabled,
    counted_accounts: v.countedAccounts,
    trend_window: v.trendWindow,
  };
}

export function SettingsPage() {
  const { data, refresh } = useData();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [player, setPlayer] = useState("");
  const [logPath, setLogPath] = useState("");
  const [updateUrl, setUpdateUrl] = useState("");
  const [autoCmdEnabled, setAutoCmdEnabled] = useState(false);
  const [autoCmdDelay, setAutoCmdDelay] = useState(3);
  const [chatKey, setChatKey] = useState(DEFAULT_CHAT_KEY);
  const [keybindMap, setKeybindMap] = useState<KeybindMap>({});
  const [keybindOverlay, setKeybindOverlay] = useState(true);
  const [overlayPlacement, setOverlayPlacement] = useState("top-center");
  const [trayEnabled, setTrayEnabled] = useState(true);
  const [countedAccounts, setCountedAccounts] = useState<string[]>([]);
  const [trendWindow, setTrendWindow] = useState(DEFAULT_TREND_WINDOW);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  // Serialized copy of what the server currently holds. Autosave compares
  // against this instead of using a "have we loaded yet" flag: the fetch sets
  // thirteen pieces of state at once, which re-runs the effect, so a flag alone
  // made every visit to this page POST the settings straight back. Comparing
  // values also means a no-op edit (retyping the same character) doesn't save.
  const lastSaved = useRef<string | null>(null);

  useEffect(() => {
    api
      .settings()
      .then((s) => {
        setSettings(s);
        setPlayer(s.player);
        setLogPath(s.log_path);
        setUpdateUrl(s.update_url);
        setAutoCmdEnabled(s.autocmd_enabled);
        setAutoCmdDelay(s.autocmd_delay_s);
        setChatKey(s.autocmd_chat_key || "/");
        setKeybindMap(s.keybind_map ?? {});
        setKeybindOverlay(s.keybind_overlay ?? true);
        setOverlayPlacement(s.overlay_placement?.preset ?? "top-center");
        setTrayEnabled(s.tray_enabled ?? true);
        const counted = (s.accounts ?? []).filter((a) => a.counted).map((a) => a.ign);
        setCountedAccounts(counted);
        setTrendWindow(s.trend_window ?? DEFAULT_TREND_WINDOW);
        // baseline for the autosave comparison — built from the SAME values we
        // just applied, so the first render after loading is a no-op
        lastSaved.current = JSON.stringify(
          settingsPayload({
            player: s.player,
            logPath: s.log_path,
            updateUrl: s.update_url,
            autoCmdEnabled: s.autocmd_enabled,
            autoCmdDelay: s.autocmd_delay_s,
            chatKey: s.autocmd_chat_key || "/",
            keybindMap: s.keybind_map ?? {},
            keybindOverlay: s.keybind_overlay ?? true,
            overlayPlacement: s.overlay_placement?.preset ?? "top-center",
            trayEnabled: s.tray_enabled ?? true,
            countedAccounts: counted,
            trendWindow: s.trend_window ?? DEFAULT_TREND_WINDOW,
          }),
        );
      })
      .catch((e) => setSaveErr(String(e)));
  }, []);

  /** Autosave: debounced, so typing a log path doesn't POST once per keystroke.
   *
   * Everything is sent together rather than per-field because the server takes
   * the whole settings object and a partial POST would be indistinguishable
   * from "the user cleared this field". The 800 ms delay is long enough to
   * cover normal typing and short enough that clicking away feels safe. */
  useEffect(() => {
    const payload = settingsPayload({
      player, logPath, updateUrl, autoCmdEnabled, autoCmdDelay, chatKey,
      keybindMap, keybindOverlay, overlayPlacement, trayEnabled,
      countedAccounts, trendWindow,
    });
    const json = JSON.stringify(payload);
    // nothing loaded yet, or nothing actually changed
    if (lastSaved.current === null || json === lastSaved.current) return;

    setSaveState("saving");
    setSaveErr(null);
    const t = window.setTimeout(() => {
      api
        .saveSettings(payload)
        .then(async () => {
          lastSaved.current = json;
          setSaveState("saved");
          // the tracker stamps keybind_status a moment later; re-read so the
          // card stops describing the bindings that were just replaced
          setSettings(await api.settings());
          // ticking an account changes every number on every page — pull fresh
          // data rather than waiting out the 15 s poll
          await refresh();
        })
        .catch((e) => {
          setSaveState("idle");
          setSaveErr(String(e));
        });
    }, 800);
    return () => window.clearTimeout(t);
  }, [
    player, logPath, updateUrl, autoCmdEnabled, autoCmdDelay, chatKey,
    keybindMap, keybindOverlay, overlayPlacement, trayEnabled, countedAccounts,
    trendWindow, refresh,
  ]);

  return (
    <div className="space-y-6 pb-24">
      <div>
        <h1 className="mb-1 text-3xl font-bold">Settings</h1>
        <p className="text-muted-foreground">App preferences and tag management.</p>
      </div>

      <Card className="space-y-4 p-5">
        <CardLabel>Identity</CardLabel>
        <div>
          <label className="mb-1 block text-sm text-muted-foreground" htmlFor="set-player">
            Minecraft name
          </label>
          <input
            id="set-player"
            className={inputCls}
            value={player}
            onChange={(e) => setPlayer(e.target.value)}
            placeholder="auto-detect (rename-proof)"
          />
          {settings && settings.detected_names.length > 0 && (
            <div className="mt-1.5 text-xs text-muted-foreground">
              detected over time: {settings.detected_names.join(", ")}
            </div>
          )}
        </div>
      </Card>

      <Card className="space-y-4 p-5">
        <CardLabel>Log source</CardLabel>
        <div>
          <label className="mb-1 block text-sm text-muted-foreground" htmlFor="set-log">
            Log file path
          </label>
          {settings && settings.clients.length > 0 && (
            <select
              className={cn(inputCls, "mb-2")}
              value=""
              onChange={(e) => e.target.value && setLogPath(e.target.value)}
            >
              <option value="">— detected clients —</option>
              {settings.clients.map((c) => (
                <option key={c.path} value={c.path}>
                  {c.label}: {c.path}
                </option>
              ))}
            </select>
          )}
          <input
            id="set-log"
            className={inputCls}
            value={logPath}
            onChange={(e) => setLogPath(e.target.value)}
            placeholder="path to latest.log"
          />
          <div className="mt-1.5 text-xs text-muted-foreground">
            Leave the tracker running while you play — games sync from this log.
          </div>
        </div>
      </Card>

      <Card className="space-y-3 p-5">
        <CardLabel>Auto commands</CardLabel>
        <label className="flex items-start gap-2.5 text-sm">
          <input
            type="checkbox"
            checked={autoCmdEnabled}
            onChange={(e) => setAutoCmdEnabled(e.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
          />
          <span>Send /locraw and /who when a game starts</span>
        </label>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          delay (seconds)
          <input
            type="number"
            min={0.5}
            max={60}
            step={0.5}
            value={autoCmdDelay}
            onChange={(e) => setAutoCmdDelay(Math.min(60, Math.max(0.5, Number(e.target.value) || 0.5)))}
            className="w-20 rounded-md border border-border bg-background px-2 py-1 text-sm text-foreground outline-none"
          />
        </label>
        <label className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          key that opens chat
          <select
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground outline-none"
            value={chatKey}
            onChange={(e) => setChatKey(e.target.value)}
          >
            {CHAT_KEY_OPTIONS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <p className="text-xs text-muted-foreground">
          Restores map + mode detection: the tracker types these two commands for you a few
          seconds into each game. Only fires while Minecraft is focused, at most once per game.
          It IS automation of two informational commands — standard overlay behaviour, but use at
          your own discretion.
        </p>
        <p className="text-xs text-muted-foreground">
          The delay above is the only wait — once it elapses both commands are typed in under
          half a second. Your chat box is open for about a tenth of a second each time, and
          anything you type in that moment goes into it, so the shorter you set the delay the
          more likely you are to be mid-keypress when it fires.
        </p>
        <p className="text-xs text-muted-foreground">
          Set the chat key to whatever you actually have bound in Minecraft
          (Options → Controls). The default &apos;/&apos; is the “Open Command” bind, which opens
          chat with the slash already typed; any other key opens chat empty and the tracker types
          the slash itself. If you rebound it and left this alone, nothing was being sent.
          Assumes a QWERTY-ish layout.
        </p>
        {/* What the last attempt actually did. Without this, a refused send
            looked identical to a successful one. */}
        {settings?.autocmd_last && (
          <div
            className={cn(
              "text-xs",
              settings.autocmd_last.startsWith("sent")
                ? "text-success"
                : settings.autocmd_last.startsWith("failed")
                  ? "text-danger"
                  : "text-muted-foreground",
            )}
          >
            last attempt: {settings.autocmd_last}
          </div>
        )}
      </Card>

      <AccountsCard
        accounts={settings?.accounts ?? []}
        counted={countedAccounts}
        onChange={setCountedAccounts}
        unattributed={settings?.unattributed_games ?? 0}
      />

      <Card className="space-y-3 p-5">
        <CardLabel>Trends</CardLabel>
        <label className="flex flex-wrap items-center gap-2 text-sm">
          Average FKDR over the last
          <select
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none"
            value={trendWindow}
            onChange={(e) => setTrendWindow(Number(e.target.value))}
          >
            {TREND_WINDOWS.map((w) => (
              <option key={w} value={w}>
                {w}
              </option>
            ))}
          </select>
          games
        </label>
        <p className="text-xs text-muted-foreground">
          A bigger window is steadier but slower to react; a smaller one moves sooner but a
          couple of lucky games shift it. 100 is a good middle. This also sets how many games
          the Trends verdict compares — it reads the last {trendWindow} against the{" "}
          {trendWindow} before them.
        </p>
      </Card>

      <Card className="space-y-3 p-5">
        <CardLabel>Window</CardLabel>
        <label className="flex items-start gap-2.5 text-sm">
          <input
            type="checkbox"
            checked={trayEnabled}
            onChange={(e) => setTrayEnabled(e.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
          />
          <span>
            Close button minimizes to the system tray
            <span className="mt-0.5 block text-xs text-muted-foreground">
              Keeps tracking after you close the window — find Rivult in the tray (bottom-right of
              the taskbar), click to reopen, right-click to exit. Turn this off to make the close
              button quit instead. Applies on the next launch.
            </span>
          </span>
        </label>
      </Card>

      <Card className="space-y-4 p-5">
        <CardLabel>Updates</CardLabel>
        <div>
          <label className="mb-1 block text-sm text-muted-foreground" htmlFor="set-upd">
            Update URL
          </label>
          <input
            id="set-upd"
            className={inputCls}
            value={updateUrl}
            onChange={(e) => setUpdateUrl(e.target.value)}
            placeholder="default (GitHub releases)"
          />
        </div>
      </Card>

      {/* Autosaves — no Save button. The status line is the only feedback that
          a change landed, so it must never be silent on failure. */}
      <div className="flex min-h-5 items-center gap-2 text-sm">
        {saveErr ? (
          <span className="text-danger">Couldn&apos;t save: {saveErr}</span>
        ) : saveState === "saving" ? (
          <span className="text-muted-foreground">Saving…</span>
        ) : saveState === "saved" ? (
          <span className="text-success">
            Saved — keybinds and overlay position apply within a couple of seconds;
            log path, name and auto-commands need a restart.
          </span>
        ) : (
          <span className="text-muted-foreground">Changes save automatically.</span>
        )}
      </div>

      <MaintenanceCard />
      <MapDetectionCard />
      <TagManagement />
      <KeybindConfig
        keymap={keybindMap}
        onChange={setKeybindMap}
        tags={data?.tags ?? []}
        status={settings?.keybind_status ?? null}
        lastPress={settings?.keybind_last ?? ""}
        overlay={keybindOverlay}
        onOverlayChange={setKeybindOverlay}
        placement={overlayPlacement}
        onPlacementChange={setOverlayPlacement}
      />
    </div>
  );
}

/** Which Minecraft accounts count toward your stats.
 *
 * Hidden entirely until there's something to choose between: with a single
 * account (the overwhelmingly common case) a chooser is just clutter. It
 * reappears the moment a second IGN shows up in the history — e.g. the first
 * time you play on an alt. */
function AccountsCard({
  accounts,
  counted,
  onChange,
  unattributed,
}: {
  accounts: AccountInfo[];
  counted: string[];
  onChange: (next: string[]) => void;
  unattributed: number;
}) {
  if (accounts.length < 2 && unattributed === 0) return null;

  const toggle = (ign: string, include: boolean) =>
    onChange(include ? [...counted, ign] : counted.filter((x) => x !== ign));

  return (
    <Card className="space-y-3 p-5">
      <CardLabel>Accounts</CardLabel>
      <p className="text-sm text-muted-foreground">
        Each game is recorded against the account that actually played it. Only ticked accounts
        count toward your stats — an alt&apos;s games stay in the database, they just don&apos;t
        pollute your numbers.
      </p>
      <div className="space-y-1">
        {accounts.map((a) => (
          <label
            key={a.ign}
            className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm hover:bg-muted/40"
          >
            <input
              type="checkbox"
              checked={counted.includes(a.ign)}
              onChange={(e) => toggle(a.ign, e.target.checked)}
              className="h-4 w-4 shrink-0 accent-primary"
            />
            <span
              className={cn(
                "flex-1",
                !counted.includes(a.ign) && "text-muted-foreground line-through",
              )}
            >
              {a.ign}
            </span>
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              {a.games} game{a.games === 1 ? "" : "s"}
            </span>
          </label>
        ))}
      </div>
      {counted.length === 0 && (
        <div className="text-sm text-danger">
          No account is ticked — your stats will be empty. Tick at least one.
        </div>
      )}
      {unattributed > 0 && (
        <p className="text-xs text-muted-foreground">
          {unattributed} game{unattributed === 1 ? "" : "s"} couldn&apos;t be matched to any
          account — those logs never recorded a kill or reward of yours, so a loss can&apos;t be
          detected in them and they don&apos;t count.
        </p>
      )}
    </Card>
  );
}

/** Re-imports every rotated log + latest.log with the current parser —
 * repairs teammates/mode/map for games the parser has since gotten smarter
 * about (content-keyed, so it never duplicates history). */
function MaintenanceCard() {
  const { refresh } = useData();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RefreshAllResult | null>(null);

  const runRefresh = async () => {
    setRunning(true);
    setResult(null);
    try {
      const r = await api.refreshAll();
      setResult(r);
      if (!r.error) await refresh();
    } catch (e) {
      setResult({ error: e instanceof Error ? e.message : String(e) });
    } finally {
      setRunning(false);
    }
  };

  return (
    <Card className="space-y-3 p-5">
      <CardLabel>Maintenance</CardLabel>
      <div className="flex items-center gap-3">
        <button
          onClick={() => void runRefresh()}
          disabled={running}
          className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm hover:bg-muted disabled:opacity-50"
        >
          <RefreshCw className={cn("h-4 w-4", running && "animate-spin")} />
          {running ? "Refreshing…" : "Full log refresh"}
        </button>
        <span className="text-xs text-muted-foreground">
          re-imports every log — takes a few minutes
        </span>
      </div>
      {result &&
        (result.error ? (
          <div className="text-sm text-danger">{result.error}</div>
        ) : (
          <div className="text-sm text-success">
            {result.ok} files · {result.games} games refreshed in {result.duration_s}s
          </div>
        ))}
      <p className="text-xs text-muted-foreground">
        Repairs anything the logs contain — it cannot restore maps for games whose log never
        printed /locraw (see Map detection above).
      </p>
    </Card>
  );
}

/** Maps come from the client's auto-/locraw chat reply. When a client update
 * stops printing it (observed 2026-07-08 on Lunar), maps silently disappear —
 * this card tells the player how to get them back instead of leaving them
 * wondering why every game says "Unknown map". */
function MapDetectionCard() {
  const { data } = useData();
  const recent = (data?.games ?? []).slice(-15);
  const missing = recent.filter((g) => !g.map).length;
  if (recent.length < 5 || missing / recent.length < 0.8) return null;
  return (
    <Card className="space-y-2 p-5">
      <CardLabel>Map detection</CardLabel>
      <p className="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-warn">
        Your recent games have no map recorded. Maps come from the game's /locraw reply, which
        your client stopped printing to chat (a client update can turn this off).
      </p>
      <p className="text-sm text-muted-foreground">
        To restore maps: in Lunar Client, enable the setting that shows server location on world
        change (Server Address / auto-locraw), or type /locraw once after joining a game. Modes
        and all other stats are unaffected.
      </p>
    </Card>
  );
}

function TagManagement() {
  const { data, createTag, deleteTag, renameTag, setTagColor } = useData();
  const [newName, setNewName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const tags = data?.tags ?? [];

  const create = async () => {
    const name = newName.trim();
    if (!name) return;
    const e = await createTag(name);
    if (e) setErr(e);
    else {
      setNewName("");
      setErr(null);
    }
  };

  const startEdit = (id: number, name: string) => {
    setEditId(id);
    setEditName(name);
    setErr(null);
  };

  const commitEdit = async (id: number) => {
    const name = editName.trim();
    setEditId(null);
    if (!name || name === tags.find((t) => t.id === id)?.name) return;
    const e = await renameTag(id, name);
    if (e) setErr(e);
    else setErr(null);
  };

  return (
    <Card className="space-y-4 p-5">
      <CardLabel>Tags</CardLabel>
      <div className="space-y-1">
        {tags.map((t) => (
          <div key={t.id} className="flex items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-muted/40">
            <TagColorPicker
              color={tagColor(t.name, t.color)}
              label={t.name}
              onPick={(c) => void setTagColor(t.id, c).then((e) => e && setErr(e))}
            />
            {editId === t.id ? (
              <input
                autoFocus
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void commitEdit(t.id);
                  if (e.key === "Escape") setEditId(null);
                }}
                onBlur={() => void commitEdit(t.id)}
                className={cn(inputCls, "h-7 flex-1 py-0")}
                aria-label={`Rename tag ${t.name}`}
              />
            ) : (
              <span className="flex-1 text-sm">{t.name}</span>
            )}
            {confirmId === t.id ? (
              <button
                onClick={() => {
                  setConfirmId(null);
                  void deleteTag(t.id).then((e) => e && setErr(e));
                }}
                onBlur={() => setConfirmId(null)}
                className="rounded bg-danger/20 px-2 py-1 text-xs font-medium text-danger"
              >
                sure? removes it from all games
              </button>
            ) : (
              editId !== t.id && (
                <>
                  <button
                    onClick={() => startEdit(t.id, t.name)}
                    className="rounded p-1 text-muted-foreground opacity-60 transition-opacity hover:text-foreground hover:opacity-100"
                    aria-label={`Rename tag ${t.name}`}
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => setConfirmId(t.id)}
                    className="rounded p-1 text-muted-foreground opacity-60 transition-opacity hover:text-danger hover:opacity-100"
                    aria-label={`Delete tag ${t.name}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </>
              )
            )}
          </div>
        ))}
        {!tags.length && <div className="text-sm text-muted-foreground">No tags yet.</div>}
      </div>
      <div className="flex items-center gap-2">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void create()}
          placeholder="new tag"
          className={cn(inputCls, "w-48")}
        />
        <button
          onClick={() => void create()}
          className="flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm hover:bg-muted"
        >
          <Plus className="h-4 w-4" /> Create
        </button>
      </div>
      {err && <div className="text-sm text-danger">{err}</div>}
      <div className="text-xs text-muted-foreground">
        letters, digits, space, - and _ · max 24 chars · pencil to rename, trash to delete (removes
        it from every game)
      </div>
    </Card>
  );
}

