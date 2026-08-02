/** First-run nudge to turn auto commands on.
 *
 * Auto commands type /locraw and /who at the start of each game. That is not a
 * nice-to-have: maps come ONLY from the /locraw reply, so without it the Maps
 * breakdown is permanently empty, and mode detection falls back to a heuristic
 * that reads Fours as Doubles about 4% of the time. A new install that never
 * finds the setting quietly gets worse data than it could, and nothing on
 * screen says so.
 *
 * Shown until either the user turns them on or dismisses it, so it can't nag
 * someone who has made their choice.
 */
import { useEffect, useState } from "react";
import { Info, X } from "lucide-react";
import { api } from "../api/client";
import { useNav } from "../state/NavContext";

export function AutoCommandNotice() {
  const [show, setShow] = useState(false);
  const { navigate } = useNav();

  useEffect(() => {
    let live = true;
    api
      .settings()
      .then((s) => {
        if (!live) return;
        setShow(!s.autocmd_enabled && !s.autocmd_notice_dismissed);
      })
      .catch(() => undefined); // a failed check just means no banner
    return () => {
      live = false;
    };
  }, []);

  const dismiss = () => {
    setShow(false); // optimistic: the banner should never feel sticky
    void api.saveSettings({ autocmd_notice_dismissed: true }).catch(() => undefined);
  };

  if (!show) return null;

  return (
    <div className="flex items-start gap-3 rounded-lg border border-warn/40 bg-warn/10 px-4 py-3 text-sm">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
      <div className="flex-1">
        <span className="font-medium">Turn on auto commands for full accuracy.</span>{" "}
        <span className="text-muted-foreground">
          They type <span className="font-mono">/locraw</span> and{" "}
          <span className="font-mono">/who</span> once per game. Maps only work with
          them on, and modes and rosters are more accurate.
        </span>
        <button
          onClick={() => navigate("Settings")}
          className="ml-1 underline underline-offset-2 hover:text-foreground"
        >
          Open Settings
        </button>
      </div>
      <button
        onClick={dismiss}
        aria-label="Dismiss"
        className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
