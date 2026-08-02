/** The shared game-list surface (THIS SESSION box + Games page).
 *
 * Interactions per the design handoff:
 *  - plain click        -> expand/collapse game detail
 *  - Ctrl/Cmd+click     -> multi-select rows, then apply a tag to all at once
 *  - right-click        -> tag menu for that game
 *  - "+ Tag" affordance -> same menu, mouse-friendly
 *  - newly detected games are highlighted (no popups)
 */
import { useState, type MouseEvent } from "react";
import { Tags, X } from "lucide-react";
import type { Game, Tag } from "../api/types";
import { cn } from "../lib/cn";
import { mmss } from "../lib/format";
import { useData } from "../state/DataContext";
import { GameDetailPanel } from "./GameDetailPanel";
import { TagBadge } from "./TagBadge";
import { TagMenu, type TagCheck } from "./TagMenu";

interface MenuState {
  x: number;
  y: number;
  gameIds: number[];
  title: string;
}

interface GamesTableProps {
  games: Game[];
  /** Ids to highlight as freshly detected. */
  highlightIds?: ReadonlySet<number>;
  /** Hide columns that don't fit narrow surfaces (Today's session box). */
  compact?: boolean;
}

const RESULT_LABEL: Record<string, { text: string; cls: string }> = {
  WIN: { text: "Win", cls: "text-success" },
  FINAL_DEATH: { text: "Loss", cls: "text-danger" },
  UNRESOLVED: { text: "?", cls: "text-warn" },
};

export function GamesTable({ games, highlightIds, compact = false }: GamesTableProps) {
  const { data, setTagOnGames, createTag, clearNewGames, resolveGame } = useData();
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const [openId, setOpenId] = useState<number | null>(null);
  const [menu, setMenu] = useState<MenuState | null>(null);
  const tags = data?.tags ?? [];
  const byId = new Map(games.map((g) => [g.id, g]));

  /** Mark-win / mark-loss / remove, offered only when the menu targets ONE
   * game that has no outcome (or one you already resolved, so you can change
   * your mind). A batch selection gets the tag menu alone. */
  const resolveActions = () => {
    if (!menu || menu.gameIds.length !== 1) return undefined;
    const g = byId.get(menu.gameIds[0]);
    if (!g) return undefined;
    const unresolved = g.result === "UNRESOLVED" || g.result_overridden;
    if (!unresolved) return undefined;
    const set = (body: Parameters<typeof resolveGame>[1]) => () =>
      void resolveGame(g.id, body);
    return [
      ...(g.result_overridden
        ? [{ label: "Clear my answer", onClick: set({ result: null, hidden: false }) }]
        : [
            { label: "Mark as win", onClick: set({ result: "WIN" as const }) },
            { label: "Mark as loss", onClick: set({ result: "FINAL_DEATH" as const }) },
          ]),
      { label: "Remove from history", onClick: set({ hidden: true }), danger: true },
    ];
  };

  const rowClick = (e: MouseEvent, g: Game) => {
    clearNewGames([g.id]); // reviewed — fade the "new" highlight
    if (e.ctrlKey || e.metaKey) {
      const next = new Set(selected);
      if (next.has(g.id)) next.delete(g.id);
      else next.add(g.id);
      setSelected(next);
    } else if (selected.size) {
      setSelected(new Set());
    } else {
      setOpenId(openId === g.id ? null : g.id);
    }
  };

  const openMenuFor = (e: MouseEvent, g: Game) => {
    e.preventDefault();
    e.stopPropagation();
    const ids = selected.has(g.id) && selected.size > 1 ? [...selected] : [g.id];
    setMenu({
      x: e.clientX,
      y: e.clientY,
      gameIds: ids,
      title: ids.length > 1 ? `Tag ${ids.length} games` : "Tag game",
    });
  };

  const checkState = (tag: Tag): TagCheck => {
    if (!menu) return "none";
    const have = menu.gameIds.filter((id) => byId.get(id)?.tags.includes(tag.name)).length;
    return have === 0 ? "none" : have === menu.gameIds.length ? "all" : "some";
  };

  const pick = async (tag: Tag, apply: boolean) => {
    if (!menu) return;
    await setTagOnGames(menu.gameIds, tag, apply);
  };

  const cols = compact
    ? "grid-cols-[1.4fr_1fr_0.7fr_0.5fr_0.5fr_0.6fr_2fr]"
    : "grid-cols-[0.9fr_1.4fr_1.2fr_0.8fr_0.6fr_0.5fr_0.5fr_0.5fr_0.5fr_0.6fr_1.6fr]";

  return (
    <div className="relative">
      {selected.size > 0 && (
        <div className="sticky top-0 z-10 flex items-center gap-3 border-b border-border bg-muted/80 px-4 py-2 text-sm backdrop-blur">
          <span className="font-medium">{selected.size} selected</span>
          <button
            onClick={(e) => {
              const r = (e.target as HTMLElement).getBoundingClientRect();
              setMenu({
                x: r.left,
                y: r.bottom + 4,
                gameIds: [...selected],
                title: `Tag ${selected.size} games`,
              });
            }}
            className="flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 hover:bg-muted transition-colors"
          >
            <Tags className="h-3.5 w-3.5" /> Apply tag
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="flex items-center gap-1 text-muted-foreground hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" /> Clear
          </button>
        </div>
      )}

      <div className={cn("grid gap-x-3 px-4 py-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground bg-muted/20", cols)}>
        {!compact && <div>Date</div>}
        <div>Map</div>
        {!compact && <div>Teammates</div>}
        <div>Mode</div>
        <div>Result</div>
        <div className="text-right" title="Final kills">FK</div>
        {!compact && <div className="text-right" title="Final deaths">FD</div>}
        {compact ? (
          <div className="text-right" title="Beds broken">Beds</div>
        ) : (
          <>
            <div className="text-right" title="Beds broken">BB</div>
            <div className="text-right" title="Your bed lost">BL</div>
          </>
        )}
        <div className="text-right">Len</div>
        <div>Tags</div>
      </div>

      <div className="divide-y divide-border/70">
        {games.map((g) => {
          const res = RESULT_LABEL[g.result] ?? RESULT_LABEL.UNRESOLVED;
          const isNew = highlightIds?.has(g.id) ?? false;
          const isSel = selected.has(g.id);
          // The log ended mid-game, so there's no outcome. Dimmed because no
          // number includes it, and labelled so it reads as "your turn" rather
          // than as an error. (Games on an un-ticked account aren't here at
          // all — the server no longer sends them.)
          const isUncounted = g.counted === false;
          return (
            <div key={g.id}>
              <div
                onClick={(e) => rowClick(e, g)}
                onContextMenu={(e) => openMenuFor(e, g)}
                title={isUncounted ? g.uncounted_reason : undefined}
                className={cn(
                  "grid cursor-pointer items-center gap-x-3 px-4 py-2 text-sm group hover:bg-muted/30",
                  "transition-colors duration-700", // new-game highlight fades out
                  cols,
                  isNew && "bg-success/10 border-l-2 border-l-success",
                  isSel && "bg-primary/30 hover:bg-primary/30",
                  isUncounted && "opacity-45 border-l-2 border-l-muted-foreground/40",
                )}
              >
                {!compact && <div className="text-muted-foreground">{g.date ?? "?"}</div>}
                <div className="font-medium flex items-center gap-2 truncate">
                  <span
                    className={cn("truncate", !g.map && "text-muted-foreground/50")}
                    title={g.map ? undefined : "No map in this game's log (see Settings → Map detection)"}
                  >
                    {g.map || "—"}
                  </span>
                  {isNew && <span className="h-2 w-2 shrink-0 rounded-full bg-success animate-pulse" title="Newly detected" />}
                  {isUncounted && (
                    <span className="shrink-0 rounded border border-warn/50 px-1 text-[10px] uppercase tracking-wide text-warn">
                      unresolved
                    </span>
                  )}
                  {g.result_overridden && (
                    <span
                      className="shrink-0 rounded border border-border px-1 text-[10px] uppercase tracking-wide text-muted-foreground"
                      title="You set this result by hand"
                    >
                      manual
                    </span>
                  )}
                </div>
                {!compact && (
                  <div className="truncate text-muted-foreground">
                    {g.teammates.join(", ") || "solo"}
                  </div>
                )}
                <div className="text-muted-foreground truncate">{g.mode ?? "?"}</div>
                <div className={cn("font-medium", res.cls)}>{res.text}</div>
                <div className="text-right font-mono">{g.your_final_kills ?? 0}</div>
                {!compact && <div className="text-right font-mono">{g.your_final_deaths ?? 0}</div>}
                <div className="text-right font-mono">{g.beds_broken ?? 0}</div>
                {!compact && (
                  <div className={cn("text-right font-mono", g.your_bed_lost ? "text-danger" : "text-muted-foreground/50")}>
                    {g.your_bed_lost ? 1 : 0}
                  </div>
                )}
                <div className="text-right font-mono text-muted-foreground">{mmss(g.duration_s)}</div>
                <div className="flex items-center gap-1.5 overflow-hidden">
                  <div className="flex items-center gap-1 overflow-hidden">
                    {g.tags.map((name) => (
                      <TagBadge key={name} name={name} color={tags.find((t) => t.name === name)?.color} />
                    ))}
                  </div>
                  <button
                    onClick={(e) => openMenuFor(e, g)}
                    className="ml-auto shrink-0 rounded border border-dashed border-muted-foreground/40 px-1.5 py-0.5 text-[11px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-foreground hover:border-muted-foreground"
                    aria-label={`Edit tags for game on ${g.map ?? "unknown map"}`}
                  >
                    {g.tags.length ? "edit" : "+ tag"}
                  </button>
                </div>
              </div>
              {openId === g.id && <GameDetailPanel gameId={g.id} />}
            </div>
          );
        })}
      </div>

      {games.length === 0 && (
        <div className="px-4 py-8 text-center text-sm text-muted-foreground">No games.</div>
      )}

      {menu && (
        <TagMenu
          tags={tags}
          position={{ x: menu.x, y: menu.y }}
          title={menu.title}
          checkState={checkState}
          onPick={(t, apply) => void pick(t, apply)}
          onCreate={createTag}
          onClose={() => setMenu(null)}
          actions={resolveActions()}
        />
      )}
    </div>
  );
}
