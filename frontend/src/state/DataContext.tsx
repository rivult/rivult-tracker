/** Global data store: one /api/dashboard fetch per global-filter change,
 * polled every POLL_MS so games detected by a running tracker appear without
 * popups (they get highlighted instead — design handoff, capture option 2).
 *
 * Tag writes are OPTIMISTIC: the local copy updates immediately (immutably),
 * the idempotent /set requests fire in the background, and the next refresh
 * reconciles with server truth. Dream modes (Armed / Totallynormal) are
 * excluded here, at the data boundary, so no page ever counts them.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "../api/client";
import {
  EMPTY_TAG_FILTER,
  type Dashboard,
  type SyncResult,
  type Tag,
  type TagFilter,
} from "../api/types";

const POLL_MS = 15_000;

/** Master paywall switch. False = everything unlocked (current state, per the
 * user: "turn off premium view lock for now"). Flip to true to re-arm the
 * Breakdowns/Trends locks, the 90-day Games clamp, and the Today trend peek —
 * the license plumbing underneath keeps working either way. */
const PAYWALL_ENABLED = false;

/** Any parenthesised suffix marks a dream mode. The parser only ever adds one
 * for a variant — from locraw's mode code, the Armed chat fingerprint, or the
 * mode's own start banner — so matching the shape rather than a fixed list of
 * names means a dream mode Hypixel invents next month is excluded on day one
 * instead of silently polluting real stats until someone updates a regex. */
const DREAM_MODE = /\(.+\)/;

/** Drop dream-mode games and modes — not considered part of real stats. */
export function stripDreamModes(d: Dashboard): Dashboard {
  return {
    ...d,
    games: d.games.filter((g) => !g.mode || !DREAM_MODE.test(g.mode)),
    modes: d.modes.filter((m) => !DREAM_MODE.test(m)),
  };
}

interface DataContextValue {
  data: Dashboard | null;
  loading: boolean;
  error: string | null;
  filter: TagFilter;
  setFilter: (f: TagFilter) => void;
  /** Game ids first seen after the initial load — the "new game" highlight. */
  newGameIds: ReadonlySet<number>;
  /** Fade a game's highlight (called when the player clicks/tags it). */
  clearNewGames: (ids: number[]) => void;
  refresh: () => Promise<void>;
  syncNow: () => Promise<SyncResult>;
  lastSync: SyncResult | null;
  syncing: boolean;
  /** Rivult cloud license — gates Breakdowns/Trends and full Games history. */
  premium: boolean;
  toggleTag: (gameId: number, tagId: number) => Promise<void>;
  /** Batch: idempotently apply/remove one tag across many games, optimistically. */
  setTagOnGames: (gameIds: number[], tag: Tag, apply: boolean) => Promise<void>;
  createTag: (name: string) => Promise<string | null>;
  deleteTag: (tagId: number) => Promise<string | null>;
  renameTag: (tagId: number, name: string) => Promise<string | null>;
  setTagColor: (tagId: number, color: string) => Promise<string | null>;
  /** Resolve a game the parser couldn't: mark it a win/loss, or remove it.
   * `result: null, hidden: false` clears the decision. */
  resolveGame: (
    gameId: number,
    body: { result?: "WIN" | "FINAL_DEATH" | null; hidden?: boolean },
  ) => Promise<string | null>;
}

const DataContext = createContext<DataContextValue | null>(null);

export function DataProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilterState] = useState<TagFilter>(EMPTY_TAG_FILTER);
  // The filter survives a restart: it's a deliberate choice ("show me only my
  // cheater games"), and having it silently reset on every launch made the app
  // look like it had forgotten. Persisted server-side so it follows the data,
  // not the browser profile.
  // Set once the user touches the filter themselves. The restore is async, so
  // without this a slow settings fetch could land AFTER a click and silently
  // undo it.
  const userChanged = useRef(false);
  useEffect(() => {
    let live = true;
    api
      .settings()
      .then((cfg) => {
        if (live && !userChanged.current && cfg.tag_filter) {
          setFilterState(cfg.tag_filter);
        }
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const setFilter = useCallback((f: TagFilter) => {
    userChanged.current = true;
    setFilterState(f);
    // fire-and-forget: failing to remember a filter must never break filtering
    api.saveSettings({ tag_filter: f }).catch(() => undefined);
  }, []);
  const [newGameIds, setNewGameIds] = useState<ReadonlySet<number>>(new Set());
  const [lastSync, setLastSync] = useState<SyncResult | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [premium, setPremium] = useState(false);

  // Seen ids survive filter changes: a game is only "new" the first time the
  // app ever sees it, not every time a filter re-reveals it.
  const seenIds = useRef<Set<number> | null>(null);
  const tagsRef = useRef<Tag[]>([]);
  const filterRef = useRef(filter);
  filterRef.current = filter;

  const refresh = useCallback(async () => {
    try {
      const d = stripDreamModes(await api.dashboard(filterRef.current, tagsRef.current));
      tagsRef.current = d.tags;
      if (seenIds.current === null) {
        // Initial load: everything is old news.
        seenIds.current = new Set(d.games.map((g) => g.id));
      } else {
        const fresh = d.games.filter((g) => !seenIds.current!.has(g.id));
        if (fresh.length) {
          for (const g of fresh) seenIds.current.add(g.id);
          setNewGameIds((prev) => new Set([...prev, ...fresh.map((g) => g.id)]));
        }
      }
      setData(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // Refetch on filter change + poll while the tab is visible.
  useEffect(() => {
    setLoading(true);
    void refresh();
  }, [filter, refresh]);

  useEffect(() => {
    const id = setInterval(() => {
      if (!document.hidden) void refresh();
    }, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  // License check: offline-first (cached server-side with a grace window).
  useEffect(() => {
    if (!PAYWALL_ENABLED) {
      setPremium(true);
      return;
    }
    let live = true;
    api
      .cloudStatus()
      .then((s) => live && setPremium(s.license.status === "active"))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const clearNewGames = useCallback((ids: number[]) => {
    setNewGameIds((prev) => {
      if (!ids.some((id) => prev.has(id))) return prev;
      const next = new Set(prev);
      for (const id of ids) next.delete(id);
      return next;
    });
  }, []);

  const syncNow = useCallback(async (): Promise<SyncResult> => {
    setSyncing(true);
    try {
      const r = await api.sync();
      setLastSync(r);
      await refresh();
      return r;
    } catch (e) {
      const r = { error: e instanceof Error ? e.message : String(e) };
      setLastSync(r);
      return r;
    } finally {
      setSyncing(false);
    }
  }, [refresh]);

  /** Optimistically rewrite the tag list of the given games (new objects only). */
  const applyLocally = useCallback((gameIds: number[], tagName: string, apply: boolean) => {
    const ids = new Set(gameIds);
    setData((prev) =>
      prev
        ? {
            ...prev,
            games: prev.games.map((g) =>
              ids.has(g.id)
                ? {
                    ...g,
                    tags: apply
                      ? g.tags.includes(tagName)
                        ? g.tags
                        : [...g.tags, tagName]
                      : g.tags.filter((n) => n !== tagName),
                  }
                : g,
            ),
          }
        : prev,
    );
  }, []);

  /** Not optimistic: resolving a game moves it between the `games` and
   * `unresolved` lists AND changes every aggregate, so a local patch would
   * have to reimplement the server's counting rules. A refetch is correct and
   * the action is rare. */
  const resolveGame = useCallback(
    async (
      gameId: number,
      body: { result?: "WIN" | "FINAL_DEATH" | null; hidden?: boolean },
    ): Promise<string | null> => {
      try {
        const r = await api.resolveGame(gameId, body);
        if (r.error) return r.error;
        await refresh();
        return null;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        return msg;
      }
    },
    [refresh],
  );

  const setTagOnGames = useCallback(
    async (gameIds: number[], tag: Tag, apply: boolean) => {
      applyLocally(gameIds, tag.name, apply);
      clearNewGames(gameIds);
      try {
        await Promise.all(gameIds.map((id) => api.setTag(id, tag.id, apply)));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        await refresh(); // roll back the optimistic state to server truth
      }
    },
    [applyLocally, clearNewGames, refresh],
  );

  const toggleTag = useCallback(
    async (gameId: number, tagId: number) => {
      await api.toggleTag(gameId, tagId);
      await refresh();
    },
    [refresh],
  );

  const createTag = useCallback(
    async (name: string): Promise<string | null> => {
      const r = await api.createTag(name);
      if (r.error) return r.error;
      await refresh();
      return null;
    },
    [refresh],
  );

  const deleteTag = useCallback(
    async (tagId: number): Promise<string | null> => {
      const r = await api.deleteTag(tagId);
      if (r.error) return r.error;
      await refresh();
      return null;
    },
    [refresh],
  );

  const renameTag = useCallback(
    async (tagId: number, name: string): Promise<string | null> => {
      const r = await api.renameTag(tagId, name);
      if (r.error) return r.error;
      await refresh();
      return null;
    },
    [refresh],
  );

  /** Optimistic: paints the new color immediately (unlike rename/create/delete,
   * which wait on refresh) since a swatch pick should feel instant. Rolls
   * back to server truth via refresh() on error. */
  const setTagColor = useCallback(
    async (tagId: number, color: string): Promise<string | null> => {
      setData((prev) =>
        prev
          ? { ...prev, tags: prev.tags.map((t) => (t.id === tagId ? { ...t, color } : t)) }
          : prev,
      );
      try {
        const r = await api.setTagColor(tagId, color);
        if (r.error) {
          await refresh();
          return r.error;
        }
        return null;
      } catch (e) {
        await refresh();
        return e instanceof Error ? e.message : String(e);
      }
    },
    [refresh],
  );

  const value = useMemo(
    () => ({
      data,
      loading,
      error,
      filter,
      setFilter,
      newGameIds,
      clearNewGames,
      refresh,
      syncNow,
      lastSync,
      syncing,
      premium,
      toggleTag,
      setTagOnGames,
      createTag,
      deleteTag,
      renameTag,
      setTagColor,
      resolveGame,
    }),
    [
      data,
      loading,
      error,
      filter,
      newGameIds,
      clearNewGames,
      refresh,
      syncNow,
      lastSync,
      syncing,
      premium,
      toggleTag,
      setTagOnGames,
      createTag,
      deleteTag,
      renameTag,
      setTagColor,
      resolveGame,
    ],
  );

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}

export function useData(): DataContextValue {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useData must be used inside DataProvider");
  return ctx;
}
