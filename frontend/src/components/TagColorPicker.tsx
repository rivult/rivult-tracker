/** Colour dot that opens a small preset palette on click — used by the
 * Settings tag rows. Duplicate colours across tags are allowed, so this
 * never dedupes or disables an already-used swatch. */
import { useEffect, useRef, useState } from "react";
import { cn } from "../lib/cn";
import { TAG_PALETTE } from "../lib/tagRegistry";

interface TagColorPickerProps {
  color: string;
  label: string;
  onPick: (color: string) => void;
}

export function TagColorPicker({ color, label, onPick }: TagColorPickerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", onDocClick);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDocClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="h-2.5 w-2.5 shrink-0 rounded-full ring-1 ring-border ring-offset-1 ring-offset-card transition-transform hover:scale-125"
        style={{ backgroundColor: color }}
        aria-label={`Change colour for ${label}`}
      />
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1.5 grid grid-cols-3 gap-1.5 rounded-lg border border-border bg-card p-2 shadow-xl shadow-black/50">
          {TAG_PALETTE.map((c) => (
            <button
              key={c}
              onClick={() => {
                onPick(c);
                setOpen(false);
              }}
              className={cn(
                "h-5 w-5 rounded-full border border-border/60 transition-transform hover:scale-110",
                c === color && "ring-2 ring-foreground ring-offset-1 ring-offset-card",
              )}
              style={{ backgroundColor: c }}
              aria-label={`Set colour ${c}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
