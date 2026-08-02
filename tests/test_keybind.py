"""Tests for global tagging keybinds (design P3, ``bedwars_parser/keybind.py``).

What can and cannot be tested here: the binding parser, the settings-map
validation, and the pending-queue lifecycle are pure logic and fully covered.
A real WM_HOTKEY keypress needs a Windows desktop session, so dispatch is
exercised through injected register/press callables instead — the same shape
``autocmd.py``'s tests use.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from bedwars_parser import keybind
from bedwars_parser.db import Store
from bedwars_parser.parse import parse_log

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "latest.log")


class ParseBindingTest(unittest.TestCase):
    def test_function_keys_need_no_modifier(self):
        mods, vk = keybind.parse_binding("F6")
        self.assertEqual(vk, 0x75)
        self.assertEqual(mods, keybind.MOD_NOREPEAT)

    def test_modifier_combo(self):
        mods, vk = keybind.parse_binding("CTRL+ALT+C")
        self.assertEqual(vk, ord("C"))
        self.assertTrue(mods & keybind.MOD_CONTROL)
        self.assertTrue(mods & keybind.MOD_ALT)
        self.assertTrue(mods & keybind.MOD_NOREPEAT)

    def test_bare_letter_is_rejected(self):
        # binding a naked letter globally would eat it in every application
        with self.assertRaises(keybind.BindingError):
            keybind.parse_binding("C")

    def test_rejects_unknown_key_and_modifier(self):
        for bad in ("", "F25", "CTRL+", "HYPER+C", "CTRL+ENTER", "++"):
            with self.assertRaises(keybind.BindingError, msg=bad):
                keybind.parse_binding(bad)

    def test_normalize_orders_and_uppercases(self):
        self.assertEqual(keybind.normalize_key("control + alt+c"), "CTRL+ALT+C")
        self.assertEqual(keybind.normalize_key("alt+ctrl+c"), "CTRL+ALT+C")
        self.assertEqual(keybind.normalize_key("f6"), "F6")


class ValidateMapTest(unittest.TestCase):
    def test_normalizes_entries(self):
        self.assertEqual(
            keybind.validate_map({"f6": "cheater", "ctrl+alt+s": "sweat"}),
            {"F6": "cheater", "CTRL+ALT+S": "sweat"})

    def test_rejects_bad_tag_charset(self):
        # tag names are rendered into the page and used in query params
        with self.assertRaises(keybind.BindingError):
            keybind.validate_map({"F6": "<script>"})

    def test_rejects_empty_tag_and_duplicate_key(self):
        with self.assertRaises(keybind.BindingError):
            keybind.validate_map({"F6": "  "})
        with self.assertRaises(keybind.BindingError):
            keybind.validate_map({"f6": "cheater", "F6": "sweat"})

    def test_rejects_too_many(self):
        many = {f"F{i}": "cheater" for i in range(1, 13)}
        keybind.validate_map(many)                     # 12 is the cap
        many["CTRL+ALT+A"] = "sweat"
        with self.assertRaises(keybind.BindingError):
            keybind.validate_map(many)

    def test_load_map_survives_corrupt_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(os.path.join(tmp, "t.db"))
            try:
                store.set_meta("keybind_map", "{not json")
                self.assertEqual(keybind.load_map(store), {})
                store.set_meta("keybind_map", json.dumps({"F6": "cheater"}))
                self.assertEqual(keybind.load_map(store), {"F6": "cheater"})
            finally:
                store.close()


class PendingQueueTest(unittest.TestCase):
    """A press mid-game queues; the tag lands once the game resolves."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")

    def tearDown(self):
        self.tmp.cleanup()

    def _store_with_games(self) -> Store:
        store = Store(self.db)
        store.sync(parse_log(FIXTURE), "s1")
        return store

    def _tags_of(self, store: Store, session_id: str, idx: int) -> list[str]:
        row = store.conn.execute(
            "SELECT id FROM games WHERE session_id=? AND idx=?",
            (session_id, idx)).fetchone()
        if not row:
            return []
        return [r["name"] for r in store.conn.execute(
            "SELECT t.name FROM tags t JOIN game_tags gt ON gt.tag_id=t.id "
            "WHERE gt.game_id=?", (row["id"],)).fetchall()]

    def _truncated_log(self) -> str:
        """A copy of the fixture cut mid-final-game, so its last game parses
        UNRESOLVED and Store.sync holds it back — the live-tail state a
        keypress actually happens in."""
        lines = open(FIXTURE, "rb").read().split(b"\n")
        starts = [i for i, ln in enumerate(lines) if b"Protect your bed" in ln]
        path = os.path.join(self.tmp.name, "partial.log")
        with open(path, "wb") as f:
            f.write(b"\n".join(lines[:starts[-1] + 12]))
        return path

    def test_queued_tag_applies_once_the_game_lands(self):
        store = Store(self.db)
        try:
            # mid-game: the 7th game is in progress, so only 6 are stored
            store.sync(parse_log(self._truncated_log()), "s1")
            self.assertEqual(self._tags_of(store, "s1", 7), [])
            self.assertIsNone(store.conn.execute(
                "SELECT id FROM games WHERE session_id='s1' AND idx=7"
            ).fetchone())

            # the press happens now, against a game that has no row yet
            keybind.queue_pending(store, "s1", 7, "cheater")
            self.assertEqual(keybind.apply_pending(store), 0)

            # game ends -> the tracker syncs -> the queued tag lands on it
            store.sync(parse_log(FIXTURE), "s1")
            self.assertEqual(keybind.apply_pending(store), 1)
            self.assertIn("cheater", self._tags_of(store, "s1", 7))
            # queue is drained, so a second pass is a no-op
            self.assertEqual(keybind.apply_pending(store), 0)
        finally:
            store.close()

    def test_repeated_press_for_same_game_queues_once(self):
        store = Store(self.db)
        try:
            keybind.queue_pending(store, "s1", 2, "cheater")
            keybind.queue_pending(store, "s1", 2, "cheater")
            rows = json.loads(store.get_meta("pending_keybind_tags"))
            self.assertEqual(len(rows), 1)
        finally:
            store.close()

    def test_unmatched_entry_survives_then_expires(self):
        store = self._store_with_games()
        try:
            keybind.queue_pending(store, "never-happened", 99, "cheater",
                                  now=1000.0)
            # game never landed: kept while fresh...
            keybind.apply_pending(store, now=1000.0 + 60)
            self.assertEqual(len(json.loads(
                store.get_meta("pending_keybind_tags"))), 1)
            # ...dropped once past the TTL, so the queue can't grow forever
            keybind.apply_pending(store, now=1000.0 + keybind.PENDING_TTL_S + 1)
            self.assertEqual(json.loads(
                store.get_meta("pending_keybind_tags")), [])
        finally:
            store.close()

    # -- the game-resolution rule (ARCHITECTURE §P3) -----------------------

    def _recent_ctx(self, session_id: str, idx: int, age_s: float,
                    now: float = 10_000.0) -> tuple:
        """A Context with no game in progress and (session, idx) having ended
        ``age_s`` ago, plus the ``now`` used to evaluate it."""
        return keybind.Context(
            current=None, last_ended=(session_id, idx),
            last_ended_at=now - age_s), now

    def test_recent_game_within_window_is_tagged(self):
        self._store_with_games().close()
        ctx, now = self._recent_ctx("s1", 3, age_s=30)
        r = keybind.press(self.db, "sweats", ctx, now=now)
        self.assertEqual(r.action, "added")
        self.assertEqual(r.scope, "recent")
        store = Store(self.db)
        try:
            self.assertIn("sweats", self._tags_of(store, "s1", 3))
        finally:
            store.close()

    def test_recent_game_outside_window_is_ignored(self):
        # ended >120s ago and nothing in progress -> "no game to tag"
        self._store_with_games().close()
        ctx, now = self._recent_ctx("s1", 3, age_s=keybind.RECENT_WINDOW_S + 1)
        r = keybind.press(self.db, "sweats", ctx, now=now)
        self.assertEqual(r.action, "none")
        store = Store(self.db)
        try:
            self.assertEqual(self._tags_of(store, "s1", 3), [])
        finally:
            store.close()

    def test_empty_context_never_tags_a_stale_game(self):
        # the crucial rule: a press at launch (no current, no witnessed end)
        # must NOT fall back to the newest game in the DB
        self._store_with_games().close()
        r = keybind.press(self.db, "sweats", keybind.Context(), now=10_000.0)
        self.assertEqual(r.action, "none")
        store = Store(self.db)
        try:
            n = store.conn.execute(
                "SELECT COUNT(*) c FROM game_tags").fetchone()["c"]
            self.assertEqual(n, 0)
        finally:
            store.close()

    def test_second_press_on_recent_game_toggles_off(self):
        # feedback exists now, so a double-press removes
        self._store_with_games().close()
        ctx, now = self._recent_ctx("s1", 3, age_s=10)
        r1 = keybind.press(self.db, "sweats", ctx, now=now)
        r2 = keybind.press(self.db, "sweats", ctx, now=now)
        self.assertEqual(r1.action, "added")
        self.assertEqual(r2.action, "removed")
        store = Store(self.db)
        try:
            self.assertEqual(self._tags_of(store, "s1", 3), [])
        finally:
            store.close()

    def test_current_game_press_queues_and_second_press_unqueues(self):
        store = Store(self.db)
        try:
            ctx = keybind.Context(current=("s1", 7))
            r1 = keybind.press(self.db, "cheater", ctx, now=1.0)
            self.assertEqual((r1.action, r1.scope), ("added", "current"))
            self.assertEqual(len(json.loads(
                store.get_meta("pending_keybind_tags"))), 1)
            r2 = keybind.press(self.db, "cheater", ctx, now=2.0)
            self.assertEqual(r2.action, "removed")
            self.assertEqual(json.loads(
                store.get_meta("pending_keybind_tags")), [])
        finally:
            store.close()

    def test_recent_tag_is_stamped_source_hotkey(self):
        self._store_with_games().close()
        ctx, now = self._recent_ctx("s1", 3, age_s=5)
        keybind.press(self.db, "cheater", ctx, now=now)
        store = Store(self.db)
        try:
            row = store.conn.execute(
                "SELECT source FROM game_tags LIMIT 1").fetchone()
            self.assertEqual(row["source"], "hotkey")
        finally:
            store.close()

    def test_resolve_target_prefers_in_progress_over_recent(self):
        ctx = keybind.Context(current=("s1", 8), last_ended=("s1", 7),
                              last_ended_at=9_999.0)
        self.assertEqual(keybind.resolve_target(ctx, 10_000.0),
                         ("current", ("s1", 8)))


class ListenerDispatchTest(unittest.TestCase):
    """Registration bookkeeping + press routing, with the Windows calls faked."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        self.presses: list = []

    def tearDown(self):
        self.tmp.cleanup()

    def _listener(self, keymap, register_fn, notify_fn=None):
        def fake_press(db, tag, context, now=None):
            self.presses.append((tag, context))
            return keybind.PressResult("added", tag, "current", f"tagged {tag}")
        return keybind.KeybindListener(
            self.db, keymap,
            register_fn=register_fn,
            unregister_fn=lambda _hid: None,
            press_fn=fake_press,
            notify_fn=notify_fn,
        )

    def _tracking_listener(self, keymap):
        """A listener that records every register/unregister id."""
        self.registered: list = []
        self.unregistered: list = []

        def reg(hid, mods, vk):
            self.registered.append(hid)
            return True

        lis = self._listener(keymap, reg)
        lis._unregister = self.unregistered.append
        return lis

    def test_rebind_replaces_the_keymap_and_releases_the_old_keys(self):
        """THE BUG: keys were registered once at startup, so changing them in
        Settings did nothing until the app was restarted."""
        lis = self._tracking_listener({"F6": "cheater"})
        lis.register_all()
        self.assertEqual([o["key"] for o in lis.status["ok"]], ["F6"])
        old_ids = list(lis._ids)

        lis._pending_map = {"F7": "sweats", "F8": "laggy"}
        lis._apply_rebind()                    # what WM_APP_REBIND triggers

        self.assertEqual(sorted(o["key"] for o in lis.status["ok"]), ["F7", "F8"])
        self.assertEqual(sorted(lis._ids.values()), ["laggy", "sweats"])
        # every previously-held key must be released, or it keeps being stolen
        # from the game by an orphaned global registration
        for hid in old_ids:
            self.assertIn(hid, self.unregistered)

    def test_rebind_dispatches_to_the_new_tags(self):
        lis = self._tracking_listener({"F6": "cheater"})
        lis.register_all()
        lis._pending_map = {"F7": "sweats"}
        lis._apply_rebind()
        lis.dispatch(next(iter(lis._ids)))
        self.assertEqual([t for t, _ in self.presses], ["sweats"])

    def test_rebind_to_an_empty_map_unbinds_everything(self):
        lis = self._tracking_listener({"F6": "cheater"})
        lis.register_all()
        lis._pending_map = {}
        lis._apply_rebind()
        self.assertEqual(lis._ids, {})
        self.assertEqual(lis.status["ok"], [])

    def test_rebind_from_an_empty_map_binds(self):
        # a fresh install has no keybinds; adding one must not need a restart
        lis = self._tracking_listener({})
        lis.register_all()
        self.assertEqual(lis.status["ok"], [])
        lis._pending_map = {"F6": "cheater"}
        lis._apply_rebind()
        self.assertEqual([o["key"] for o in lis.status["ok"]], ["F6"])

    def test_rebind_always_releases_the_waiter(self):
        # rebind() blocks on this event; a failure here would hang the tracker
        lis = self._tracking_listener({"F6": "cheater"})
        lis.register_all()
        lis.rebound.clear()
        lis._pending_map = None                # nothing queued
        lis._apply_rebind()
        self.assertTrue(lis.rebound.is_set())

    def test_dispatch_routes_to_the_bound_tag(self):
        listener = self._listener({"F6": "cheater", "F7": "laggy"},
                                  lambda *_: True)
        listener.register_all()
        self.assertEqual(len(listener.status["ok"]), 2)

        ids = sorted(listener._ids)          # sorted(keymap) -> F6=1, F7=2
        listener.dispatch(ids[0])
        listener.dispatch(ids[1])
        self.assertEqual([t for t, _ in self.presses], ["cheater", "laggy"])

    def test_dispatch_passes_the_current_context(self):
        listener = self._listener({"F6": "cheater"}, lambda *_: True)
        listener.register_all()
        listener.set_context(("s1", 3), None, 0.0)
        listener.dispatch(next(iter(listener._ids)))
        self.assertEqual(self.presses[0][1].current, ("s1", 3))
        # a new context replaces it
        listener.set_context(None, ("s1", 3), 500.0)
        listener.dispatch(next(iter(listener._ids)))
        self.assertIsNone(self.presses[1][1].current)
        self.assertEqual(self.presses[1][1].last_ended, ("s1", 3))

    def test_notify_receives_the_result(self):
        seen: list = []
        listener = self._listener({"F6": "cheater"}, lambda *_: True,
                                  notify_fn=seen.append)
        listener.register_all()
        listener.dispatch(next(iter(listener._ids)))
        self.assertEqual(seen[0].action, "added")
        self.assertEqual(seen[0].tag, "cheater")

    def test_a_failing_notify_does_not_break_dispatch(self):
        def boom(_r):
            raise RuntimeError("overlay died")
        listener = self._listener({"F6": "cheater"}, lambda *_: True,
                                  notify_fn=boom)
        listener.register_all()
        # dispatch must still return a result despite the overlay throwing
        r = listener.dispatch(next(iter(listener._ids)))
        self.assertEqual(r.action, "added")

    def test_unknown_hotkey_id_is_ignored(self):
        listener = self._listener({"F6": "cheater"}, lambda *_: True)
        listener.register_all()
        self.assertIsNone(listener.dispatch(999))
        self.assertEqual(self.presses, [])

    def test_one_failed_registration_does_not_lose_the_others(self):
        # F6 held by another app; F7 must still work
        def register(hid, _mods, vk):
            return vk != 0x75          # 0x75 = F6

        listener = self._listener({"F6": "cheater", "F7": "laggy"}, register)
        status = listener.register_all()
        self.assertEqual([o["key"] for o in status["ok"]], ["F7"])
        self.assertEqual(status["failed"][0]["key"], "F6")
        self.assertIn("already in use", status["failed"][0]["reason"])

    def test_invalid_binding_is_reported_not_raised(self):
        listener = self._listener({"F6": "cheater"}, lambda *_: True)
        listener.keymap = {"F25": "cheater"}     # bypasses validate_map
        status = listener.register_all()
        self.assertEqual(status["ok"], [])
        self.assertEqual(status["failed"][0]["key"], "F25")


if __name__ == "__main__":
    unittest.main()
