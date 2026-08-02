/** Global tagging keybinds (design P3) — bind a key to a tag so you can mark
 * a game mid-match without alt-tabbing.
 *
 * The listener lives in the tracker process (bedwars_parser/keybind.py); this
 * card only edits the map and echoes back what the tracker reported. Changes
 * apply on the next app start, which the card says out loud rather than
 * leaving the player wondering why nothing bound.
 */
import { useState, type Dispatch, type SetStateAction } from "react";
import { Keyboard, Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { KeybindMap, KeybindStatus, Tag } from "../api/types";
import { KeyCaptureButton } from "../components/KeyCaptureButton";
import { Card, CardLabel } from "../components/shared";
import { cn } from "../lib/cn";
import { tagColor } from "../lib/format";
import { SAFE_FKEYS } from "../lib/keyCapture";
import { TAG_REGISTRY, type TagRegistryEntry } from "../lib/tagRegistry";

const FKEYS = Array.from({ length: 24 }, (_, i) => `F${i + 1}`);

const MAX_BINDINGS = 12;

const selectCls =
  "rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus:border-muted-foreground/60";

/** One row per built-in tag: color swatch, current binding (or "not bound"),
 * and a press-a-key control — the quick way to rebind the four default tags
 * without going through the freeform row below. */
function RegistryTagRow({
  entry,
  keymap,
  tags,
  onChange,
}: {
  entry: TagRegistryEntry;
  keymap: KeybindMap;
  tags: Tag[];
  onChange: Dispatch<SetStateAction<KeybindMap>>;
}) {
  const currentBinding = Object.entries(keymap).find(([, v]) => v === entry.label)?.[0] ?? null;
  // the colour the user actually picked, not the registry's seed value
  const stored = tags.find((t) => t.name === entry.label);
  const swatch = tagColor(entry.label, stored?.color ?? null);

  /** This row owns EVERY key currently bound to entry.label — rebinding
   * consolidates to the one new key rather than leaving a stale duplicate. */
  const setBinding = (newBinding: string | null) => {
    onChange((prev) => {
      const next: KeybindMap = {};
      Object.entries(prev).forEach(([k, v]) => {
        if (v === entry.label) return;
        next[k] = v;
      });
      if (newBinding) next[newBinding] = entry.label;
      return next;
    });
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span
        className="h-2.5 w-2.5 shrink-0 rounded-full"
        style={{ backgroundColor: swatch }}
        aria-hidden
      />
      <span className="w-32 shrink-0 text-sm">{entry.label}</span>
      <KeyCaptureButton
        binding={currentBinding}
        onChange={setBinding}
        label={`Set the key for ${entry.label}`}
      />
      {currentBinding && (
        <button
          onClick={() => setBinding(null)}
          className="rounded p-1 text-muted-foreground opacity-60 transition-opacity hover:text-danger hover:opacity-100"
          aria-label={`Unbind ${entry.label}`}
        >
          <Trash2 className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

/** Where the notification appears. Six edge presets for now — the plan is a
 * drag-to-place editor with snapping guides later, which is why the value is
 * stored as an object server-side and not a bare string. */
const PLACEMENTS = [
  { value: "top-left", label: "Top left" },
  { value: "top-center", label: "Top centre" },
  { value: "top-right", label: "Top right" },
  { value: "bottom-left", label: "Bottom left" },
  { value: "bottom-center", label: "Bottom centre" },
  { value: "bottom-right", label: "Bottom right" },
];

/** Position picker plus a live preview, so the choice can be judged without
 * starting a game. The overlay runs in the tracker, so the preview goes through
 * the server and reports honestly when no tracker is attached. */
function OverlayPlacementRow({
  placement,
  onChange,
}: {
  placement: string;
  onChange: (next: string) => void;
}) {
  const [msg, setMsg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const preview = async () => {
    setMsg(null);
    try {
      const r = await api.testOverlay();
      setFailed(!r.ok);
      setMsg(r.ok ? "Sent — watch that corner of your screen." : (r.error ?? "Couldn't show it."));
    } catch (e) {
      setFailed(true);
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="space-y-1.5 pl-7">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">position</span>
        <select
          className={selectCls}
          value={placement}
          aria-label="Overlay position"
          onChange={(e) => onChange(e.target.value)}
        >
          {PLACEMENTS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
        <button
          onClick={() => void preview()}
          className="rounded-md border border-border bg-card px-2.5 py-1.5 text-xs hover:bg-muted"
        >
          Show me
        </button>
      </div>
      {msg && (
        <div className={cn("text-xs", failed ? "text-danger" : "text-muted-foreground")}>
          {msg}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Saved changes apply to the next notification — no restart needed.
      </p>
    </div>
  );
}

interface Props {
  keymap: KeybindMap;
  /** Takes React's updater form: every edit derives from the previous map, so
   * two clicks in one render tick can't both compute the same "free" key and
   * collapse into a single row. */
  onChange: Dispatch<SetStateAction<KeybindMap>>;
  tags: Tag[];
  status: KeybindStatus | null;
  lastPress: string;
  overlay: boolean;
  onOverlayChange: (v: boolean) => void;
  placement: string;
  onPlacementChange: (v: string) => void;
}

export function KeybindConfig({
  keymap,
  onChange,
  tags,
  status,
  lastPress,
  overlay,
  onOverlayChange,
  placement,
  onPlacementChange,
}: Props) {
  // Each registry tag gets its own quick-rebind row (below); the freeform
  // list only shows what's left, so a registry tag doesn't render twice. Only
  // the FIRST key bound to a given registry label is "owned" by its row — an
  // extra second binding to the same tag (an edge case) still shows here
  // rather than silently disappearing.
  const ownedKeys = new Set<string>();
  for (const entry of TAG_REGISTRY) {
    const owned = Object.entries(keymap).find(([, tag]) => tag === entry.label);
    if (owned) ownedKeys.add(owned[0]);
  }
  const allRows = Object.entries(keymap);
  const rows = allRows.filter(([binding]) => !ownedKeys.has(binding));
  const canAdd = allRows.length < MAX_BINDINGS && tags.length > 0;

  /** Rewrite immutably, preserving order. Keyed by the binding STRING (an
   * object's keys are already unique) rather than array index — that keeps
   * these correct regardless of which subset of the map is on screen. */
  const replaceRow = (oldBinding: string, newBinding: string, tag: string) => {
    onChange((prev) => {
      const next: KeybindMap = {};
      Object.entries(prev).forEach(([k, v]) => {
        if (k === oldBinding) next[newBinding] = tag;
        else next[k] = v;
      });
      return next;
    });
  };

  const removeRow = (binding: string) => {
    onChange((prev) => {
      const next = { ...prev };
      delete next[binding];
      return next;
    });
  };

  const addRow = () => {
    onChange((prev) => {
      const used = new Set(Object.keys(prev));
      const free = [...SAFE_FKEYS, ...FKEYS].find((k) => !used.has(k));
      return free ? { ...prev, [free]: tags[0].name } : prev;
    });
  };

  return (
    <Card className="space-y-3 p-5">
      <CardLabel>Tagging keybinds</CardLabel>
      <p className="text-sm text-muted-foreground">
        Press a key mid-game to tag the game you&apos;re playing. If a game is in progress the tag
        is queued and lands the moment that game ends; for about two minutes after a game ends it
        tags that game. Otherwise the press is ignored (no game to tag). Pressing the same key
        again removes the tag.
      </p>

      <div className="space-y-1.5">
        {TAG_REGISTRY.map((entry) => (
          <RegistryTagRow
            key={entry.id}
            entry={entry}
            keymap={keymap}
            tags={tags}
            onChange={onChange}
          />
        ))}
      </div>

      <div className="border-t border-border/60 pt-3">
        <CardLabel>Custom keybinds</CardLabel>
      </div>

      <div className="space-y-1.5">
        {rows.map(([binding, tag]) => (
          <div key={binding} className="flex flex-wrap items-center gap-2">
            <KeyCaptureButton
              binding={binding}
              onChange={(next) => replaceRow(binding, next, tag)}
              label={`Set the key that tags ${tag}`}
            />
            <span className="text-sm text-muted-foreground">tags</span>
            <select
              className={selectCls}
              value={tag}
              aria-label="Tag"
              onChange={(e) => replaceRow(binding, binding, e.target.value)}
            >
              {tags.map((t) => (
                <option key={t.id} value={t.name}>
                  {t.name}
                </option>
              ))}
              {!tags.some((t) => t.name === tag) && <option value={tag}>{tag}</option>}
            </select>
            <button
              onClick={() => removeRow(binding)}
              className="rounded p-1 text-muted-foreground opacity-60 transition-opacity hover:text-danger hover:opacity-100"
              aria-label={`Remove keybind ${binding}`}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
        {!rows.length && (
          <div className="text-sm text-muted-foreground">
            {tags.length ? "No keybinds set." : "Create a tag first — keybinds bind to tags."}
          </div>
        )}
      </div>

      <button
        onClick={addRow}
        disabled={!canAdd}
        className="flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm hover:bg-muted disabled:opacity-50"
      >
        <Plus className="h-4 w-4" /> Add keybind
      </button>

      <label className="flex items-start gap-2.5 text-sm">
        <input
          type="checkbox"
          checked={overlay}
          onChange={(e) => onOverlayChange(e.target.checked)}
          className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
        />
        <span>
          Show an on-screen confirmation when a keybind fires
          <span className="mt-0.5 block text-xs text-muted-foreground">
            A rounded pill slides in with the tag&apos;s colour as a dot, since a keypress shows
            nothing in-game. It makes no sound.
          </span>
        </span>
      </label>

      {overlay && (
        <OverlayPlacementRow placement={placement} onChange={onPlacementChange} />
      )}

      <KeybindStatusLine status={status} lastPress={lastPress} />

      <p className="text-xs text-muted-foreground">
        Click a key button and press the key you want. Letters, digits and punctuation need a
        modifier (hold Ctrl+Alt) — bound bare, they&apos;d be swallowed in every application,
        chat included.
      </p>

      <p className="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-warn">
        A bound key is taken <em>exclusively</em> while the tracker runs — Minecraft and other
        apps stop receiving it entirely. That includes capture software: a bare F-key can break
        Medal or OBS if they use the same one, which is why the defaults are Ctrl+Alt combos.
        F6–F10 are free on Minecraft&apos;s own binds; F1–F5, F11 and F12 are not.
      </p>
    </Card>
  );
}

/** What the tracker actually managed to bind, plus the last press — the only
 * feedback available, since a keypress produces nothing visible in-game. */
function KeybindStatusLine({
  status,
  lastPress,
}: {
  status: KeybindStatus | null;
  lastPress: string;
}) {
  if (!status && !lastPress) return null;
  const failed = status?.failed ?? [];
  return (
    <div className="space-y-1 text-xs">
      {status?.error && <div className="text-warn">{status.error}</div>}
      {!!status?.ok.length && (
        <div className={cn("text-success")}>
          <Keyboard className="mr-1 inline h-3.5 w-3.5" />
          bound: {status.ok.map((o) => `${o.key} → ${o.tag}`).join(", ")}
        </div>
      )}
      {failed.map((f) => (
        <div key={f.key} className="text-danger">
          {f.key} could not bind — {f.reason}
        </div>
      ))}
      {lastPress && <div className="text-muted-foreground">last press: {lastPress}</div>}
    </div>
  );
}
