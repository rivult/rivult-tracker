/** Reading a keypress into a binding string.
 *
 * The names and modifier order must match keybind.py::normalize_key; that
 * cross-language contract is enforced by tests/test_key_capture_sync.py. These
 * cover the mapping and every rejection path.
 */
import { describe, expect, it } from "vitest";
import { bindingFromEvent, bindingWarning, needsModifier } from "../keyCapture";

const press = (code: string, mods: Partial<{ ctrl: boolean; alt: boolean; shift: boolean }> = {}) =>
  bindingFromEvent({
    code,
    ctrlKey: !!mods.ctrl,
    altKey: !!mods.alt,
    shiftKey: !!mods.shift,
  });

describe("bindingFromEvent", () => {
  it("reads a bare F-key", () => {
    expect(press("F6")).toEqual({ kind: "binding", binding: "F6" });
    expect(press("F24")).toEqual({ kind: "binding", binding: "F24" });
  });

  it("emits modifiers in CTRL+ALT+SHIFT order regardless of press order", () => {
    // normalize_key sorts them; a different order here would round-trip to a
    // different string and orphan the row on the next render
    expect(press("F7", { shift: true, alt: true, ctrl: true })).toEqual({
      kind: "binding",
      binding: "CTRL+ALT+SHIFT+F7",
    });
  });

  it("maps letters, digits and the numpad", () => {
    expect(press("KeyC", { ctrl: true, alt: true })).toEqual({
      kind: "binding",
      binding: "CTRL+ALT+C",
    });
    expect(press("Digit4", { ctrl: true })).toEqual({
      kind: "binding",
      binding: "CTRL+4",
    });
    expect(press("Numpad5")).toEqual({ kind: "binding", binding: "NUMPAD5" });
    expect(press("NumpadAdd")).toEqual({ kind: "binding", binding: "ADD" });
  });

  it("maps the named keys to the tracker's spellings", () => {
    expect(press("PageUp")).toEqual({ kind: "binding", binding: "PAGEUP" });
    expect(press("Backquote", { ctrl: true })).toEqual({
      kind: "binding",
      binding: "CTRL+BACKTICK",
    });
    expect(press("Equal", { ctrl: true })).toEqual({
      kind: "binding",
      binding: "CTRL+PLUS",
    });
  });

  it("keeps waiting while only a modifier is held", () => {
    for (const code of ["ControlLeft", "AltRight", "ShiftLeft", "MetaLeft"]) {
      expect(press(code, { ctrl: true })).toEqual({ kind: "pending" });
    }
  });

  it("cancels on Escape", () => {
    expect(press("Escape")).toEqual({ kind: "cancel" });
  });

  it("refuses a bare letter, digit or punctuation key", () => {
    for (const code of ["KeyC", "Digit4", "Slash"]) {
      const r = press(code);
      expect(r.kind).toBe("error");
      if (r.kind === "error") expect(r.message).toMatch(/needs a modifier/);
    }
  });

  it("refuses a key the tracker can't bind", () => {
    // Space/Enter/Tab/arrows are deliberately unbindable — stealing them
    // globally would break the game and Windows both
    for (const code of ["Space", "Enter", "Tab", "ArrowUp", "CapsLock"]) {
      expect(press(code, { ctrl: true, alt: true }).kind).toBe("error");
    }
  });
});

describe("needsModifier", () => {
  it("is false for F-keys and the navigation/numpad cluster", () => {
    expect(needsModifier("F6")).toBe(false);
    expect(needsModifier("INSERT")).toBe(false);
    expect(needsModifier("NUMPAD0")).toBe(false);
  });

  it("is true for letters, digits and punctuation", () => {
    expect(needsModifier("C")).toBe(true);
    expect(needsModifier("4")).toBe(true);
    expect(needsModifier("SLASH")).toBe(true);
  });
});

describe("bindingWarning", () => {
  it("warns about F-keys Minecraft uses", () => {
    expect(bindingWarning("F3")).toMatch(/Minecraft/);
    expect(bindingWarning("F11")).toMatch(/Minecraft/);
  });

  it("warns that most keyboards can't send F13+", () => {
    expect(bindingWarning("F13")).toMatch(/can't send/);
    expect(bindingWarning("F24")).toMatch(/can't send/);
  });

  it("says nothing about the safe keys", () => {
    for (const b of ["F6", "F10", "CTRL+ALT+C", "NUMPAD0"]) {
      expect(bindingWarning(b)).toBe("");
    }
  });

  it("looks at the key, not the modifiers", () => {
    expect(bindingWarning("CTRL+ALT+F3")).toMatch(/Minecraft/);
  });
});
