# Rivult Bedwars Tracker

A stats tracker for Hypixel BedWars that reads your Minecraft chat log.
No Hypixel API key, no login, no account — nothing leaves your PC.

### [→ Download the latest build](https://github.com/rivult/rivult-tracker/releases/latest)

Windows only. Put the `.exe` in its own folder before running it — it keeps its
database next to itself.

---

**This repository holds downloads, not source.** The app is closed-source while
it's in early testing. Releases here are what the app's built-in updater checks,
so keep it as your download source.

### What it does

- Imports your entire BedWars history from old rotated logs on first run, then
  follows new games live
- Per-game stats: FKDR, win rate, beds, final kills, and how those move over time
- Tag games with a keybind mid-match (my mistake, teammate diff, sweats, cheater)
  and filter by them later
- Breakdowns by mode, map, party size, time of day
- Updates itself once installed

### Heads up

It isn't code-signed, so Windows SmartScreen will warn on first run and a couple
of antivirus engines flag it as a generic heuristic. Both are expected for a
PyInstaller-packaged app from an unknown publisher. The README inside the
download explains this properly rather than asking you to just trust it.

### Feedback

**contact@rivult.net** — bug reports especially. If something breaks, attach
`rivult.log` from next to the exe.
