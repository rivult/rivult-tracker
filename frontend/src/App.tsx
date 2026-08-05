import { useEffect, useRef } from "react";
import { Header } from "./components/Header";
import { LockedPage } from "./components/Locked";
import { Sidebar, type PageName } from "./components/Sidebar";
import { CLOUD_ENABLED } from "./lib/features";
import { useSmoothScroll } from "./lib/useSmoothScroll";
import { DataProvider, useData } from "./state/DataContext";
import { NavProvider, useNav } from "./state/NavContext";
import { TodayPage } from "./pages/TodayPage";
import { GamesPage } from "./pages/GamesPage";
import { BreakdownsPage } from "./pages/BreakdownsPage";
import { TrendsPage } from "./pages/TrendsPage";
import { PersonalBestsPage } from "./pages/PersonalBestsPage";
import { BridgingPage } from "./pages/BridgingPage";
import { SnapshotPage } from "./pages/SnapshotPage";
import { AccountPage, CommunityPage, SettingsPage, UpdatesPage } from "./pages/MetaPages";

/** Pages the global tag filter scopes. Personal Bests is absolute (records
 * don't change with a filter), so it greys out alongside the meta pages. */
const FILTERED_PAGES: PageName[] = ["Today", "Games", "Breakdowns", "Trends", "Snapshot"];

const PAGES: Record<PageName, () => React.JSX.Element> = {
  Today: TodayPage,
  Games: GamesPage,
  Breakdowns: BreakdownsPage,
  Trends: TrendsPage,
  "Personal Bests": PersonalBestsPage,
  Bridging: BridgingPage,
  Snapshot: SnapshotPage,
  Account: AccountPage,
  Settings: SettingsPage,
  Updates: UpdatesPage,
  Community: CommunityPage,
};

/** Premium-only pages for the free tier — Today keeps the peek. */
const PREMIUM_PAGES: PageName[] = ["Breakdowns", "Trends"];

const PREMIUM_BLURBS: Partial<Record<PageName, string>> = {
  Breakdowns:
    "See exactly what wins you games — every stat split by map, teammate, time of day, game flow and your own tags.",
  Trends:
    "Watch your FKDR move over time — week-by-week form and daily history as far back as your logs reach.",
};

function Content({ page, onNavigate }: { page: PageName; onNavigate: (p: PageName) => void }) {
  const { premium } = useData();
  // Nav state is restored from browser history, so an entry saved before the
  // cloud UI was hidden could still point at Account. Fall back rather than
  // render a page whose every call fails.
  if (!CLOUD_ENABLED && page === "Account") {
    const Today = PAGES.Today;
    return <Today />;
  }
  if (!premium && PREMIUM_PAGES.includes(page)) {
    return (
      <LockedPage
        title={page}
        blurb={PREMIUM_BLURBS[page] ?? ""}
        onGoToAccount={() => onNavigate("Account")}
      />
    );
  }
  const Page = PAGES[page];
  return <Page />;
}

function Shell() {
  const { current, navigate } = useNav();
  const page = current.page;
  const mainRef = useRef<HTMLElement>(null);
  useSmoothScroll(mainRef);

  // Reset the scroll position per view, detail included — landing halfway
  // down a breakdown you just opened reads as a rendering bug. Instant on
  // purpose: an eased scroll-to-top on every navigation feels sluggish.
  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0, behavior: "instant" });
  }, [page, current.detail]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <Header filterApplies={FILTERED_PAGES.includes(page)} />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar active={page} onNavigate={navigate} />
        <main ref={mainRef} className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-5xl px-8 py-8 xl:max-w-6xl 2xl:max-w-7xl">
            <Content page={page} onNavigate={navigate} />
          </div>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <DataProvider>
      <NavProvider>
        <Shell />
      </NavProvider>
    </DataProvider>
  );
}
