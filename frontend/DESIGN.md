Here's the revised handoff.

---

# Rivult Bedwars Tracker — design handoff v2

## What it is
Dark-themed desktop Bedwars stat reviewer built on the player's own game logs (not API polling). Core differentiator: **tag-based self-analysis** — players tag games (cheaters, laggy, rushed, etc.) and compare performance across tags. Colors undecided except one rule: **green = good, red = bad** (improvement/decline, above/below).

## App frame (established — from wireframes)

**Header bar** — one line, full width, top of app.
- Far left: app name "Rivult Bedwars Tracker."
- Center: population toggle, segmented, three states: **All – Untagged – Tagged**.
- Right of toggle: **tag filter dropdown** (include/exclude specific tags; scales as tags grow).
- This filter is **global and persistent** across Today / Games / Breakdowns / Trends. Active state must be clearly visible at all times. Grayed out (not hidden) on pages where it doesn't apply (Account, Settings, Updates, Community).
- **Date range is NOT in the header** — it's a per-page control (Breakdowns, Trends) so different pages can hold different windows simultaneously.

**Sidebar** — fixed left column.
- Group 1 (stats): Today · Games · Breakdowns · Trends · Personal Bests.
- Horizontal divider.
- Group 2 (meta): Account · Settings · Updates · Community.
- Active page highlighted.
- Account = cloud sync/identity. Settings = app prefs + tag management (create/rename/delete). Updates = changelog. Community = feedback-in + share-card export/gallery.

**Content region** — single centered column right of sidebar. Side margins adapt to window size so the column stays centered. Grids **reflow** on narrow windows (4-wide → 2-wide) rather than shrinking cells.

## Today (established — detailed, top to bottom)

1. **Date caption** — top of column. Date only, no clock ("Today is Aug 14, 2026"). Small light label, not a boxed panel.

2. **FKDR hero** — directly below, the largest element on the page. Session FKDR as a big number with an **improvement/decline arrow** (green up / red down). Deliberately oversized — FKDR is the number players care about; this is an identity choice. Stays wide-not-square as the window narrows. No toggle on the hero — the header filter re-scopes it along with the whole page.

3. **Stat grid** — 4 columns × 3 rows, with strict **column alignment**: each column is numerator / denominator / ratio.
   - Column 1: Wins → Losses → **WLR**
   - Column 2: Final Kills → Final Deaths → **FKDR**
   - Column 3: Beds Broken → Beds Lost → **BBLR**
   - Column 4: Kills → Deaths → **KDR**
   - Row 1 = good counts, row 2 = bad counts, row 3 = the ratio each pair produces, sitting directly beneath it. This vertical logic is the point — preserve it.
   - KDR kept for column symmetry but **visually de-emphasized** (smallest cell; weakest signal in Bedwars).
   - On reflow, columns stay intact as pairs (never separate a ratio from its counts).

4. **Mid pair** — two boxes side by side.
   - Left: **7-day FKDR bar graph** — one bar per *played* day (days not played are skipped, not shown as zero), so the slope reads honestly.
   - Right: **Tagged games numbers** — per-tag stats: each tag with its game count and key numbers. Not a duplicate of the header toggle (that's binary all/tagged/untagged; this box breaks it out per individual tag).

5. **THIS SESSION** — full-width box, bottom of page. Today's games listed as rows. This is the tagging **review/correction surface** (primary tagging happens live during play — see capture options). Behaviors:
   - Games newly detected as finished (from the live log) are **highlighted** in the list — no popups.
   - **Ctrl+click to multi-select rows**, then apply a tag to all selected games at once.
   - Each row has an easy edit affordance to change/remove tags.
   - Last position is intentional: payoff (stats) up top, double-check (games) at the bottom.

## Games (content settled — visual model to come from you)
Dense, table-like, grouped by session (expandable). Each row: map · teammate(s) · mode · win/loss · finals · kills · beds broken · beds lost · length · tags. **No per-game FKDR** (meaningless at n=1). Local filters (map, mode, result, teammate) layered on top of the global header filter. **Ctrl+click multi-select for batch tagging**, same as THIS SESSION.

## Breakdowns (structure settled — visual model to come from you)
**Hub-and-detail structure**: the Breakdowns landing page is a grid of **section cards** — e.g. Diamonds/mid control, Misc items, Maps, Teammates, Game flow, Kill quality, Session position, Time — and clicking a card opens that section's dedicated breakdown page. The card grid is the extensibility mechanism: adding a new breakdown = adding a card, no restructuring.

Every detail page is the **same reusable component**: sorted table + bar chart. Each row: name · games · FKDR · W/L · beds. Controls: **min-games threshold** (hide small-sample noise) + **date-range chips (7d / 30d / all)** — the range is a *filter* here ("does this pattern still hold lately"), never the axis.

Dimension pool to distribute across cards — **[log]** = auto-derived, **[tag]** = requires tagging:
- [log] map · teammate synergy · mode · partied vs solo-queue · time of day · day of week
- [log] broke first bed vs not · own bed fell first vs held · first frag vs not · fast vs slow start · rush vs grind (length buckets) · comeback wins · post-bed survival
- [log] finals vs regular kills · kills before vs after bed loss · first-kill conversion · nemesis players · in-game kill streaks
- [log] warmup vs fatigue (game 1–3 vs 10+) · after-win vs after-loss
- [tag] diamonds/mid control · rushed vs greeded · defended vs roamed · solo-carry vs teamplay · tryhard vs chill · any custom tag (new tags appear automatically)

## Trends (content settled — visual model to come from you)
Time is the **axis** here (vs Breakdowns where it's a filter — that distinction is what keeps them separate pages).
- Landing visual: **contribution graph** — month grid of played days, cell color-coded by that day's FKDR, hover shows the value.
- Below: FKDR-over-time line, week-average cards, daily breakdown list.
- Range chips (7d / 30d / all). Single-mode; never blend modes into one line.

## Personal Bests (content settled — visual model to come from you)
Featured hero record (biggest, celebrated) + grid of same-style celebration blocks. Each block: the number, record name, date set. **Scale-forever records only** — single-game count records are capped by lobby size, so they're out. The list:
- Single-game: **fastest win** (the only uncapped single-game record).
- Streaks: longest win streak · longest single-session win streak.
- Session: best session FKDR · most finals in a session · most games in a session.
- Milestones: lifetime total finals · beds broken · wins · games.

## Tag capture (three player options, effort/accuracy ladder)
1. **Tag after, from memory** — zero setup, always available. Surface = THIS SESSION box. Good for memorable tags, lossy for subtle ones.
2. **App open while playing** — app auto-detects game end from the live log and **highlights the new game** in the list (no popups). Player tags it between games. Shares machinery with option 1; build these together first.
3. **Global keybind during the game** — assumed working. Configurable keybind (not hardcoded), registration checked so conflicts surface instead of failing silently. Ships with a **one-time notice screen with an OK button**: keybind may not work in true fullscreen → use borderless or option 2.

## Stat conventions
FKDR → W/L (never win %) → beds lost → finals is the importance order. Beds always split as **broken** (offense) vs **lost** (defense). Green = good, red = bad — the only color rule locked.

## Open decisions for next session
1. Visual models for Games, Breakdowns (hub cards + detail), Trends, Personal Bests — you're sketching these.
2. Option 3 keybind: one "flag game" key vs a small keymap (F1 = cheater, F2 = laggy…). Multi-key is more useful but needs a keymap config in Settings.
3. Frontend stack (decides the hotkey API and packaging).
4. Share-card export placement: buttons per surface vs inside Community.
5. Pricing placeholder only: ~$3.99/mo, ~$30/yr annual-pushed. Not a build blocker.

## Standing context
Parser proving a fixture is still the true build gate. Capture options 1+2 before 3. Validate with one player tagging for two weeks before optimizing price. The rivult content brand is the distribution channel — tool and content are one flywheel.

---

Ready to paste. Sleep first.