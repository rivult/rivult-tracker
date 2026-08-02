/** Set a keybind by pressing the key.
 *
 * Replaces the modifier+key dropdown pair. Arming installs a window-level
 * keydown listener with preventDefault, so the captured combo doesn't also
 * trigger the browser (Ctrl+P, F5 and friends). Bare modifiers keep it waiting;
 * Escape cancels; an unbindable combo shows why and stays armed so the next
 * press is the retry.
 */
import { useEffect, useState } from "react";
import { Keyboard } from "lucide-react";
import { bindingFromEvent, bindingWarning } from "../lib/keyCapture";
import { cn } from "../lib/cn";

interface Props {
  /** Current binding, or null when nothing is bound yet. */
  binding: string | null;
  onChange: (binding: string) => void;
  label?: string;
}

export function KeyCaptureButton({ binding, onChange, label }: Props) {
  const [arming, setArming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!arming) return;
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const r = bindingFromEvent(e);
      if (r.kind === "pending") return;
      if (r.kind === "cancel") {
        setArming(false);
        setError(null);
        return;
      }
      if (r.kind === "error") {
        setError(r.message);
        return;
      }
      setError(null);
      setArming(false);
      onChange(r.binding);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [arming, onChange]);

  const warning = binding ? bindingWarning(binding) : "";

  return (
    <span className="inline-flex flex-col gap-0.5">
      <button
        onClick={() => {
          setError(null);
          setArming((a) => !a);
        }}
        aria-label={label ?? (arming ? "Press a key" : "Change keybind")}
        className={cn(
          "flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-xs transition-colors",
          arming
            ? "border-success/60 bg-success/10 text-success"
            : "border-border bg-card hover:bg-muted",
          !binding && !arming && "text-muted-foreground",
        )}
      >
        <Keyboard className="h-3.5 w-3.5" />
        {arming ? "press a key… (Esc cancels)" : (binding ?? "not bound")}
      </button>
      {error && <span className="max-w-xs text-xs text-danger">{error}</span>}
      {!error && warning && (
        <span className="max-w-xs text-xs text-warn">{warning}</span>
      )}
    </span>
  );
}
