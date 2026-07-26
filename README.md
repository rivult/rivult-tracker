# Rivult Bedwars Tracker

A stats tracker for Hypixel BedWars that reads your Minecraft chat log.
No API key, no login, no account — nothing leaves your PC.

## [⬇ Download for Windows](https://github.com/rivult/rivult-tracker/releases/latest)

> **Early test build.** It works, but it's rough in places and I want to know
> where. Bug reports to **contact@rivult.net** — see [Feedback](#feedback).

---

## Setup

**1. Put the `.exe` in its own folder** — e.g. `Desktop\RivultTracker`.

This matters. It creates its database and log file *next to itself*, so if you
leave it in Downloads your stats end up scattered in there. If you move the exe
later, move the whole folder or you'll leave your history behind.

**2. Double-click it.**

**3. Windows will say "Windows protected your PC."** Click **More info** →
**Run anyway**. This happens because the app isn't code-signed — a certificate
costs a few hundred a year and I'd like to find out whether anyone actually
uses this first. Your antivirus might also flag it; there's an
[honest explanation](#about-the-antivirus-warnings) below.

**4. The dashboard opens.** No console window — progress goes to `rivult.log`
next to the exe.

### First run takes a minute or two

It imports your entire BedWars history from your old rotated log files. That
can take 1–2 minutes, longer if you have years of logs, and **the dashboard
will look empty until it finishes**. Just leave it running. After that it
follows your games live — play one and it shows up a few seconds after it ends.

### If it stays empty

It auto-detects Lunar, vanilla/Forge/Fabric, Badlion, Prism and MultiMC. If
nothing appears after a few minutes, go to **Settings → Log source** and either
pick your client from the list or paste the path to your `latest.log`.

---

## Things that aren't obvious

### Closing minimises to the tray

Clicking **X** doesn't quit — it hides to a tray icon (bottom-right, you may
need the little `^` arrow) and **keeps tracking in the background**.

- Left-click the icon to reopen
- Right-click → **Exit** to actually quit
- Launching the exe again while it's hidden just reopens it, it won't start a
  second copy
- Prefer X to quit outright? **Settings → Window**

### Tagging games with a keybind

**Settings → Tagging keybinds.** Four tags come pre-bound:

| Tag | Key |
| --- | --- |
| my mistake | `Ctrl+Alt+F6` |
| teammate diff | `Ctrl+Alt+F7` |
| sweats | `Ctrl+Alt+F8` |
| cheater | `Ctrl+Alt+F9` |

Press one during a game and it tags that game without alt-tabbing. A small
popup slides down from the top of your screen in the tag's colour saying e.g.
*"tagged cheater"* — it shows over fullscreen.

- Press mid-game → the tag lands when that game ends
- Press within ~2 minutes after a game → tags that game
- Otherwise it's ignored ("no game to tag")
- Press the same key again to **remove** the tag

Two gotchas:

- **A bound key is taken exclusively while the tracker runs.** Minecraft and
  everything else stop receiving it. That includes capture software — a bare
  F-key will break Medal or OBS, which is why the defaults are `Ctrl+Alt`
  combos.
- **Restart the app after changing a keybind.** They're registered at startup.

You're not limited to F-keys: letters, digits, numpad, Insert, Home, Page Up
and so on all work (letters and digits need a modifier).

### Updates

From v0.5.2 on it updates itself. When a new build is out, the **Updates** page
shows an *Install & restart* button that downloads it and swaps itself in. It
won't interrupt a game in progress. Install this first one by hand; after that
you shouldn't need to come back here.

---

## Known gaps

- **Cloud sync and accounts aren't in this build.** They're written but the
  server isn't live, so the UI is hidden rather than showing you a page that
  only ever errors. Everything works fully offline.
- **Map names are missing on some games.** Hypixel only prints the map if
  `/locraw` ran during the game. **Settings → Auto commands** can send it for
  you automatically.
- **Alt accounts** are detected separately and only your main counts toward
  your stats. Tick others on in **Settings → Accounts** if you want them
  included.

---

## About the antivirus warnings

A couple of engines flag this. They're false positives, but I'd rather explain
than tell you to trust me.

The app is a Python program packaged into an `.exe` with a tool called
PyInstaller. That packaging is also popular with real malware, so scanners are
suspicious of it by default — Microsoft's flag for it literally ends in `!ml`,
meaning a machine-learning guess rather than an actual match.

It also genuinely does a few things that look alarming without context: it
reads Minecraft's log file, watches a fixed set of eight movement keys for the
bridging analyser, can type `/locraw` for you if you turn that on, and can
replace its own `.exe` when updating.

What it does **not** do: it doesn't capture text or passwords (the key watcher
is limited to WASD / shift / space / mouse and physically can't read letters),
it doesn't touch your Minecraft account, and nothing is uploaded anywhere.

I'm working on reducing the flags — the real fix is a code-signing certificate,
which I'll buy if enough people use this. If you'd rather not run an unsigned
app, that's a completely reasonable call.

---

## Your data

Everything lives in `bedwars.db` next to the exe. Nothing is uploaded. To
uninstall: right-click the tray icon → **Exit**, then delete the folder.

---

## Feedback

**contact@rivult.net** — the address is also in the app under Updates.

Bug reports beat compliments. **If something crashed or looked wrong, attach
`rivult.log` from next to the exe** — that's where all the errors go, and it's
usually the difference between me fixing it and me guessing.

Things I'd especially like to hear about:

- Did it find your log on its own, or did you have to set it manually?
- How long did the first import take, and how many games did it find?
- Do the numbers match what you'd expect — FKDR, wins, final kills?
- Did closing to the tray work, and did reopening and Exit both behave?
- Did a keybind fire in-game and did you see the popup? Which key, and were
  you fullscreen or borderless?
- Anything that looks wrong, empty, or confusing.
