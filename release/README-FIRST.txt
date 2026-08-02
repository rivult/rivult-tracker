RIVULT BEDWARS TRACKER — test build v0.11.0
===========================================

Thanks for testing. This reads your Minecraft chat log and turns it into
per-game stats you can tag and filter. No Hypixel API, no login, nothing
leaves your PC.


NEW IN 0.11.0
-------------
* DO THIS ONCE AFTER UPDATING: Settings -> Maintenance -> Full log refresh.
  Dream modes now produce games that never parsed before.
* TRENDS REBUILT. It's now one verdict sentence -- "you're improving, 6.70
  FKDR over your last 100 games, up from 4.71" -- and one chart, with a dashed
  LINE OF BEST FIT showing how fast you're moving in FKDR per 100 games.
* The chart now plots against GAMES PLAYED, not dates. A 100-game window can
  be ten days or two months depending on how much you queued, and a date axis
  made those look identical.
* Gone: the range picker, the 25-500 window slider, week averages and the
  daily table. The window moved to Settings. Focused sessions is now an
  overlay on the same chart instead of a second one.
* DREAM MODES (Lucky Blocks, Ultimate, Swappage...) are tracked again. They
  print their own start banner instead of "Protect your bed", so they used to
  produce no game at all and keybinds did nothing during one. They stay out
  of your stats -- they aren't the same game.
* FIXED: "couldn't save" during a full log refresh -- reprocessing held one
  transaction open across every game, so anything else writing hit "database
  is locked".
* FIXED: a crash on the first launch after an update (several database
  connections racing the same schema migration).
* FIXED: the tag filter chip read "-1" when a tag was hidden. Now "1 hidden".


NEW IN 0.10.0
-------------
* DO THIS ONCE AFTER UPDATING: Settings -> Maintenance -> Full log refresh.
  Six of the new breakdowns read data that didn't exist before and stay empty
  until your logs are re-read.
* SIX NEW BREAKDOWNS: How You Die (void vs players, every death not just the
  final one), Diamond Economy, Kill Participation (are you carrying?), Streak
  State (do you tilt?), Day & Time, Early Economy.
* Upgrades now lists EVERY upgrade -- Haste, forges, Heal Pool, traps -- not
  just protection tier. Misc Items went from 7 categories to 18; Fireball and
  Golden Apple were the two most-bought items and neither was tracked.
* Game Flow rebuilt. Its old "bed held" row won 99.6% of the time, because
  holding your bed and winning are nearly the same thing -- it was measuring
  itself. Now shows who broke the first bed and whether yours fell early.
* "Partied vs Solo-queue" REMOVED. The log can't answer it honestly: a win
  names your team in chat and a loss doesn't, so the buckets split by whether
  you won, not by whether you premade.
* SETTINGS SAVE THEMSELVES -- the Save button is gone.
* Games: one search box that finds any player including opponents. Alt-account
  games are hidden instead of greyed. Games the log cut off can be marked a
  win/loss or removed, and your answer survives a log refresh.
* Trends: baseline numbers up top, a window slider instead of chips, and a
  second line over only the sessions you tag.
* FIXED: a crash on the first launch after an update (several database
  connections ran the same migration at once and all but one failed).

ON 0.9.x? Use Updates -> Install & restart.


NEW IN 0.9.1
------------
* CHANGING A KEYBIND NOW WORKS. Keys were only registered when the app
  started, so rebinding a tag key in Settings left the app still listening on
  the OLD key -- the new one did nothing until you restarted. Keybinds (and
  the overlay position) now apply within a couple of seconds of saving.
  Setting your FIRST keybind on a fresh install needed a restart too; also
  fixed. Tagging itself was never broken -- only changing which key does it.

READ THE 0.9.0 NOTES BELOW TOO if you're coming from 0.8.0 or older -- there's
a one-time full log refresh you need to run.


NEW IN 0.9.0
------------
* DO THIS ONCE AFTER UPDATING: Settings -> Maintenance -> Full log refresh.
  The alt fix below can only repair games already in your database by
  re-reading your logs (takes a few minutes).
* ALT ACCOUNTS ARE COUNTED PROPERLY. When your Slumber Ticket pouch is full,
  Hypixel stops printing the line the tracker used to identify you by -- so
  games on that account were filed under nobody: left out of every stat, kills
  and beds recorded as 0, and LOSSES INVISIBLE. Identity now reads every
  reward type. Beds broken had the same bug and is fixed too.
  Alt games still only count once you tick the account on in Settings ->
  Accounts; that part is on purpose.
* AUTO COMMANDS NOW ACTUALLY TYPE. They never did on a 64-bit build -- the
  Windows call was given a wrong structure size and failed silently every
  time. Settings now shows what the last attempt did.
* THE KEYBIND POPUP NO LONGER BEEPS. A Windows sound was firing on every tag
  press during a game. It's also been redesigned: a rounded pill in the app's
  own black with the tag's colour as a dot, and you can pick which corner it
  appears in (Settings, with a "Show me" preview button).
* Search for any player in the Games filter bar -- opponents included, not
  just your teammates.
* Set a tagging keybind by pressing the key instead of picking from a list.

ON 0.8.0? Use Updates -> Install & restart.


NEW IN 0.8.0
------------
* YOUR FULL GAME HISTORY IS BACK. Games played on an alt, or games where the
  log never identified anyone, used to be hidden completely -- so the history
  looked like it had holes in it. They're now shown greyed out with a "not
  counted" label and a tooltip saying why. Your stats are unchanged: those
  games are still excluded from every number, they're just visible again.
* Your tag filter is remembered between launches instead of resetting.
* AUTO COMMANDS: you can now set which key opens chat (Settings -> Auto
  commands). If you rebound Minecraft's "Open Command" key away from '/',
  auto commands were silently doing nothing -- this is the fix.

ON 0.7.2? Use Updates -> Install & restart. On anything older, install by
hand: the old auto-updater was broken and can't fix itself.


IF AN EARLIER BUILD WOULDN'T OPEN AT ALL -- FIXED IN 0.7.1
----------------------------------------------------------
Windows tags files you download, and Explorer copies that tag onto everything
it extracts from a downloaded zip. .NET then refuses to load the tagged DLLs,
so the window never appeared and rivult.log showed
"Failed to resolve Python.Runtime.Loader.Initialize".

Rivult now clears that tag from its own files at startup. Nothing to do.

(If you ever hit it again on some other download: right-click the ZIP ->
Properties -> tick "Unblock" -> Apply, THEN extract. Doing it after extracting
is too late -- the tag is already on each file.)


WHAT CHANGED IN 0.7.0
---------------------
* TRENDS: the window chips (50/100/200/500) genuinely didn't work before --
  the average was computed after filtering to the date range, so every
  window held the same games. Fixed. Your career FKDR is now drawn on the
  chart as the line to beat, and "pace" is quoted per 100 games instead of
  per day played.
* BRIDGING: blocks/sec was counting right-clicks, so double-clicking made it
  read about double -- 5.5-5.8 blocks/sec, faster than sprinting, which is
  impossible while sneaking. Speed now comes from your sneak rhythm (one
  sneak = one block), so it doesn't care how you click. It also shows how
  you click, how you compare to god-bridge pace, and a "what's costing you"
  panel worked out from your timing.
  Note the tracker reads your inputs, not the game -- it can't see the
  bridge or a fall, so that panel points at the block where the timing went
  wrong, not the moment you came off.


IF YOU ARE COMING FROM 0.5.2 (the single .exe)
----------------------------------------------
The app is now a FOLDER instead of a single .exe, and your stats now live
somewhere separate from the app.

* Extract the whole RivultTracker folder and keep it together. The exe needs
  the "_internal" folder next to it — copying the exe out on its own will
  not work.
* Your database now lives in:
      %LOCALAPPDATA%\Rivult
  (paste that into the Explorer address bar). If you had 0.5.2, its
  bedwars.db is moved there automatically the first time 0.7.0 starts — you
  don't lose your history, and you don't need to do anything.
* Because of that, you can now move or delete the app folder without losing
  your stats.

Why the change: the single-exe build unpacked itself into a temp folder on
every launch, which is the same trick a lot of malware uses, and it was a
big reason antivirus flagged the app. This build doesn't do that.


HOW TO RUN
----------
1. Extract the zip. You get a folder called RivultTracker.
2. Put that folder wherever you want it (e.g. Desktop). Keep it intact.
3. Run RivultTracker.exe inside it.
4. Windows will show "Windows protected your PC" -> click "More info" ->
   "Run anyway". This happens because the app isn't code-signed (a signing
   certificate costs a few hundred a year, and I want to find out whether
   people actually use this first). It's expected, not a virus. See the
   ANTIVIRUS note at the bottom.
5. The dashboard window opens. There's no console window — progress and
   errors go to rivult.log in %LOCALAPPDATA%\Rivult.


FIRST RUN TAKES A MINUTE
------------------------
On first launch it imports your entire BedWars history from your old
rotated log files. That can take 1-2 minutes (longer if you have years of
logs) and the dashboard will look empty until it finishes. Just leave it
running.

After that it follows your game live — play a BedWars game and it appears
within a few seconds of the game ending.


IT NEEDS TO FIND YOUR LOG
-------------------------
It auto-detects Lunar, vanilla/Forge/Fabric, Badlion, Prism and MultiMC.
If the dashboard stays empty after a few minutes, go to Settings and check
"Log source" — pick the right client from the list, or paste the path to
your latest.log manually.


CLOSING = MINIMIZE TO TRAY
--------------------------
Clicking the X does NOT quit. It hides the window to a tray icon (bottom-
right of the taskbar, you may need to click the little "^" to see it) and
KEEPS TRACKING your games in the background.
* Left-click the tray icon to reopen the dashboard.
* Right-click it -> Exit to actually quit.
* Launching the app again while it's in the tray just reopens it — it won't
  start a second copy.
If you'd rather the X just quit, turn it off in Settings -> Window.


TAGGING KEYBINDS
----------------
Settings -> Tagging keybinds. The four default tags (my mistake, teammate
diff, sweats, cheater) come pre-bound to Ctrl+Alt+F6 .. Ctrl+Alt+F9. Press
one during a game to tag it without alt-tabbing.
* Press it mid-game -> the tag lands the moment that game ends.
* Press it within ~2 minutes after a game ends -> it tags that game.
* Otherwise the press is ignored ("no game to tag").
* Press the same key again to REMOVE the tag.

You get a confirmation each time: a small popup slides down from the top of
the screen in that tag's colour, saying e.g. "tagged cheater". It shows over
fullscreen. You can turn it off, or rebind any tag, in Settings.

Things to know:
* A bound key is taken EXCLUSIVELY while the tracker runs — Minecraft and
  other apps stop receiving it entirely. That includes capture software: a
  bare F-key can break Medal or OBS, which is why the defaults are Ctrl+Alt
  combos.
* Restart the app after changing keybinds — they're registered at startup.
* You are NOT limited to F-keys: letters, digits, numpad, Insert, Home,
  Page Up and so on all work (letters/digits need a modifier).


UPDATES
-------
The app updates itself. When a new build is out, the Updates page shows an
"Install & restart" button that downloads it and swaps the folder over. It
won't interrupt a game in progress, and if the swap fails it puts your old
version back rather than leaving you with nothing.

If you're on 0.6.0 already, use Updates -> Install & restart; this is the
first release that can arrive that way. Coming from 0.5.2 or earlier, install
this one by hand -- your stats are picked up automatically either way.


KNOWN GAPS
----------
* Cloud sync / accounts are not in this build. It's built but the server
  isn't live, so I've hidden it rather than show you a page that only ever
  errors. Everything works fully offline; your data stays on your PC.
* Map names are missing on some games. Hypixel only prints the map if
  /locraw ran during the game. Settings -> "Auto commands" can type it for
  you automatically if you want to test that.
* Alt accounts are tracked separately and only your main counts toward your
  stats. Tick others on in Settings -> Accounts.


WHAT I WANT TO KNOW
-------------------
* Did it find your log on its own, or did you have to set it manually?
* How long did the first-run import take, and how many games did it find?
* Do the numbers match what you'd expect (FKDR, wins, final kills)?
* IF YOU UPGRADED FROM 0.5.2: did your old stats carry over?
* TRAY: did closing minimize to the tray and keep tracking? Did reopening
  and Exit both work? Did a second launch reopen the running one?
* KEYBINDS: did a keybind fire in-game, and did you see the popup? Which
  key, and were you fullscreen or borderless?
* Anything that looks wrong, empty, or confusing.
* If it crashes or acts up: send me rivult.log from %LOCALAPPDATA%\Rivult —
  that's where all the errors go.


ANTIVIRUS -- the honest explanation
-----------------------------------
Some antivirus engines flag this app. They're false positives, but I'd
rather explain than ask you to just trust me.

The app is a Python program packaged into an .exe with a tool called
PyInstaller. That packaging is also popular with actual malware, so scanners
are suspicious of it by default -- Microsoft's flag for it literally ends in
"!ml", meaning a machine-learning guess rather than a real match. This build
switched away from the single-file format specifically to reduce that, since
the self-extracting behaviour was part of what looked suspicious.

On top of that, Rivult genuinely does a few things that look alarming out of
context: it reads Minecraft's log file, watches a fixed set of 8 movement
keys for the bridging analyser, can type /locraw for you if you enable it,
and can replace its own folder when updating. All legitimate, all things
malware also does.

What it does NOT do: it doesn't capture text or passwords (the key watcher
is limited to WASD/shift/space/mouse and can't read letters), it doesn't
touch your Minecraft account, and nothing leaves your PC.

The real fix is a code-signing certificate, which I'll buy if enough people
use this. If you'd rather not run an unsigned app, that's a completely
reasonable call.


FEEDBACK -- please do
---------------------
This is an early build and I want to know what's wrong with it.

    contact@rivult.net

Bug reports beat compliments. If something crashed or looked wrong, attach
rivult.log from %LOCALAPPDATA%\Rivult -- that's where the errors go.
The app also has this address under Updates -> Feedback.


YOUR DATA
---------
Everything lives in %LOCALAPPDATA%\Rivult. Nothing is uploaded. To
uninstall: right-click the tray icon -> Exit, delete the RivultTracker
folder, then delete %LOCALAPPDATA%\Rivult.
