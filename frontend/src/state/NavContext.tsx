/** Navigation: which page, and which sub-view within it.
 *
 * The browser's own history is the source of truth rather than a stack we
 * keep ourselves — that way the mouse back button, which browsers map to
 * history.back(), works without us reimplementing forward/back semantics.
 * Each entry rides in `history.state`, so popstate can restore it exactly.
 *
 * Sub-views (a Breakdowns section, a Bridging session) live here instead of
 * in page-local state for one reason: something *outside* the page — the
 * sidebar, the back button — has to be able to leave them.
 *
 * URLs are deliberately untouched (pushState with no url argument). The app
 * is a local desktop window; adding real routes would mean a router and
 * refresh semantics for no gain here.
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
import type { PageName } from "../components/Sidebar";

export interface NavEntry {
  page: PageName;
  /** Sub-view key within the page: a breakdown section, a bridging session. */
  detail?: string;
}

interface HistoryState {
  rivult: NavEntry;
  depth: number;
}

interface NavValue {
  current: NavEntry;
  /** Go to a page's ROOT view. Clicking the sidebar entry for the page you're
   * already in — but inside a detail — therefore returns you to its hub. */
  navigate: (page: PageName) => void;
  /** Open a sub-view of the current page. */
  openDetail: (detail: string) => void;
  back: () => void;
  canGoBack: boolean;
}

const INITIAL: NavEntry = { page: "Today" };

const NavContext = createContext<NavValue | null>(null);

/** Mouse back (X1) fallback: browsers normally turn it into history.back()
 * themselves. We only act if no popstate arrived, so the two can't stack up
 * into a double-back in whichever shell we're running under. */
const MOUSE_BACK_GRACE_MS = 60;
const MOUSE_BACK_BUTTON = 3;

function sameEntry(a: NavEntry, b: NavEntry): boolean {
  return a.page === b.page && (a.detail ?? null) === (b.detail ?? null);
}

export function NavProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<NavEntry>(INITIAL);
  const [depth, setDepth] = useState(0);
  const depthRef = useRef(0);
  depthRef.current = depth;
  const currentRef = useRef(current);
  currentRef.current = current;

  const push = useCallback((entry: NavEntry) => {
    if (sameEntry(currentRef.current, entry)) return;
    const next: HistoryState = { rivult: entry, depth: depthRef.current + 1 };
    window.history.pushState(next, "");
    setCurrent(entry);
    setDepth(next.depth);
  }, []);

  const navigate = useCallback((page: PageName) => push({ page }), [push]);

  const openDetail = useCallback(
    (detail: string) => push({ page: currentRef.current.page, detail }),
    [push],
  );

  const back = useCallback(() => window.history.back(), []);

  useEffect(() => {
    // seed the entry we're standing on so a later back() restores it
    window.history.replaceState({ rivult: INITIAL, depth: 0 } as HistoryState, "");

    let popstateAt = 0;
    const onPopState = (e: PopStateEvent) => {
      popstateAt = Date.now();
      const state = e.state as HistoryState | null;
      setCurrent(state?.rivult ?? INITIAL);
      setDepth(state?.depth ?? 0);
    };

    const onMouseUp = (e: MouseEvent) => {
      if (e.button !== MOUSE_BACK_BUTTON) return;
      e.preventDefault();
      const firedAt = Date.now();
      window.setTimeout(() => {
        // the shell already handled it natively — don't go back twice
        if (popstateAt >= firedAt) return;
        if (depthRef.current > 0) window.history.back();
      }, MOUSE_BACK_GRACE_MS);
    };

    window.addEventListener("popstate", onPopState);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("popstate", onPopState);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  const value = useMemo<NavValue>(
    () => ({ current, navigate, openDetail, back, canGoBack: depth > 0 }),
    [current, navigate, openDetail, back, depth],
  );

  return <NavContext.Provider value={value}>{children}</NavContext.Provider>;
}

export function useNav(): NavValue {
  const ctx = useContext(NavContext);
  if (!ctx) throw new Error("useNav must be used inside NavProvider");
  return ctx;
}
