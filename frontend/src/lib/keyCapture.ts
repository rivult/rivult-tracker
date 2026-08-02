/** Turn a real keypress into a binding string the tracker accepts.
 *
 * Keybinds used to be assembled from two dropdowns — a modifier list and a
 * ~90-entry key list. Pressing the key you want is both faster and the only
 * way to be sure the key you picked is one your keyboard actually sends (the
 * dropdown happily offered F13–F24, which almost no keyboard can emit).
 *
 * The names emitted here must be exactly the ones
 * `bedwars_parser/keybind.py::parse_binding` accepts, and the modifier order
 * must match `normalize_key` (CTRL, ALT, SHIFT). `tests/test_key_capture_sync.py`
 * enforces both against the Python side.
 */

/** KeyboardEvent.code -> the tracker's key name. */
export const CODE_TO_KEY: Record<string, string> = {
  // F1–F24 (mirrors _FKEYS)
  ...Object.fromEntries(
    Array.from({ length: 24 }, (_, i) => [`F${i + 1}`, `F${i + 1}`]),
  ),
  // letters and digits (bare ones need a modifier — see needsModifier)
  ...Object.fromEntries(
    Array.from({ length: 26 }, (_, i) => [
      `Key${String.fromCharCode(65 + i)}`,
      String.fromCharCode(65 + i),
    ]),
  ),
  ...Object.fromEntries(Array.from({ length: 10 }, (_, i) => [`Digit${i}`, String(i)])),
  // navigation cluster (mirrors _NAMED_KEYS)
  Insert: "INSERT",
  Delete: "DELETE",
  Home: "HOME",
  End: "END",
  PageUp: "PAGEUP",
  PageDown: "PAGEDOWN",
  ScrollLock: "SCROLLLOCK",
  Pause: "PAUSE",
  // numpad
  ...Object.fromEntries(
    Array.from({ length: 10 }, (_, i) => [`Numpad${i}`, `NUMPAD${i}`]),
  ),
  NumpadMultiply: "MULTIPLY",
  NumpadAdd: "ADD",
  NumpadSubtract: "SUBTRACT",
  NumpadDecimal: "DECIMAL",
  NumpadDivide: "DIVIDE",
  // punctuation (always needs a modifier)
  Semicolon: "SEMICOLON",
  Equal: "PLUS",
  Comma: "COMMA",
  Minus: "MINUS",
  Period: "PERIOD",
  Slash: "SLASH",
  Backquote: "BACKTICK",
  BracketLeft: "LBRACKET",
  Backslash: "BACKSLASH",
  BracketRight: "RBRACKET",
  Quote: "QUOTE",
};

/** Keys RegisterHotKey may claim on their own. Everything else would be eaten
 * in every application, including Minecraft's chat box. Mirrors the
 * `standalone_ok` logic in parse_binding. */
const STANDALONE = new Set<string>([
  ...Array.from({ length: 24 }, (_, i) => `F${i + 1}`),
  "INSERT",
  "DELETE",
  "HOME",
  "END",
  "PAGEUP",
  "PAGEDOWN",
  "SCROLLLOCK",
  "PAUSE",
  ...Array.from({ length: 10 }, (_, i) => `NUMPAD${i}`),
  "MULTIPLY",
  "ADD",
  "SUBTRACT",
  "DECIMAL",
  "DIVIDE",
]);

/** Free on Minecraft's default binds — the rest steal a key the game uses. */
export const SAFE_FKEYS = new Set(["F6", "F7", "F8", "F9", "F10"]);

const MODIFIER_CODES = /^(Control|Alt|Shift|Meta)(Left|Right)?$/;

export function needsModifier(key: string): boolean {
  return !STANDALONE.has(key);
}

export type CaptureResult =
  | { kind: "binding"; binding: string }
  /** A bare modifier — keep waiting rather than reporting an error. */
  | { kind: "pending" }
  | { kind: "cancel" }
  | { kind: "error"; message: string };

/** Read one keydown. Pure, so the mapping and every rejection is testable. */
export function bindingFromEvent(e: {
  code: string;
  ctrlKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
}): CaptureResult {
  if (e.code === "Escape") return { kind: "cancel" };
  if (MODIFIER_CODES.test(e.code)) return { kind: "pending" };

  const key = CODE_TO_KEY[e.code];
  if (!key) {
    return {
      kind: "error",
      message: "That key can't be bound. Try an F-key, a letter or digit with a modifier, or a key like Insert or Home.",
    };
  }
  const mods: string[] = [];
  if (e.ctrlKey) mods.push("CTRL");
  if (e.altKey) mods.push("ALT");
  if (e.shiftKey) mods.push("SHIFT");
  if (!mods.length && needsModifier(key)) {
    return {
      kind: "error",
      message: `${key} needs a modifier (hold Ctrl+Alt) or it would be captured in every application.`,
    };
  }
  return { kind: "binding", binding: [...mods, key].join("+") };
}

/** Advice about the captured key, shown under the row. "" when there's none. */
export function bindingWarning(binding: string): string {
  const key = binding.split("+").pop() ?? "";
  if (/^F(1[3-9]|2[0-4])$/.test(key)) {
    return "Most keyboards can't send this key — bind it only if yours can.";
  }
  if (/^F\d+$/.test(key) && !SAFE_FKEYS.has(key)) {
    return "Minecraft uses this key by default.";
  }
  return "";
}
