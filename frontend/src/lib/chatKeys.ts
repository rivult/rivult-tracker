/** Keys that can open Minecraft's chat box, mirroring CHAT_KEYS in
 * bedwars_parser/autocmd.py. Kept in sync by tests/test_chat_keys_sync.py —
 * a key offered here that the backend rejects would silently do nothing.
 *
 * These only ever OPEN chat. What gets typed afterwards is the fixed pair
 * /locraw and /who, and nothing else.
 */
export const DEFAULT_CHAT_KEY = "/";

export const CHAT_KEY_OPTIONS: { value: string; label: string }[] = [
  { value: "/", label: "/  (default — Open Command)" },
  { value: "t", label: "T  (default — Open Chat)" },
  { value: "y", label: "Y" },
  { value: "u", label: "U" },
  { value: "i", label: "I" },
  { value: "p", label: "P" },
  { value: "f", label: "F" },
  { value: "g", label: "G" },
  { value: "j", label: "J" },
  { value: "k", label: "K" },
  { value: "z", label: "Z" },
  { value: "x", label: "X" },
  { value: "v", label: "V" },
  { value: "b", label: "B" },
  { value: "n", label: "N" },
  { value: "m", label: "M" },
  { value: "comma", label: ","},
  { value: "period", label: "." },
  { value: "semicolon", label: ";" },
  { value: "apostrophe", label: "'" },
];
