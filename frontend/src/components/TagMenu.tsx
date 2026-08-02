/** Tag picker popover — used by row right-click, the row "+ Tag" affordance,
 * and the batch-selection bar. Checked state per tag is provided by the
 * caller ("all" = every target game has it, "some" = mixed).
 */
import { useEffect, useRef, useState } from "react";
import { Check, Minus, Plus } from "lucide-react";
import type { Tag } from "../api/types";
import { cn } from "../lib/cn";
import { tagColor } from "../lib/format";

export type TagCheck = "all" | "some" | "none";

interface TagMenuProps {
  tags: Tag[];
  position: { x: number; y: number };
  checkState: (tag: Tag) => TagCheck;
  /** Clicking a tag: apply when currently none/some, remove when all. */
  onPick: (tag: Tag, apply: boolean) => void;
  onCreate?: (name: string) => Promise<string | null>;
  onClose: () => void;
  title?: string;
  /** Optional commands shown ABOVE the tag list, separated by a rule. Used for
   * resolving a game the parser couldn't (mark win / loss / remove), which
   * belongs on the same right-click rather than in a second menu. */
  actions?: MenuAction[];
}

export interface MenuAction {
  label: string;
  onClick: () => void;
  danger?: boolean;
}

export function TagMenu({ tags, position, checkState, onPick, onCreate, onClose, title, actions }: TagMenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [newName, setNewName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Keep the menu on screen.
  const [pos, setPos] = useState(position);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setPos({
      x: Math.min(position.x, window.innerWidth - r.width - 8),
      y: Math.min(position.y, window.innerHeight - r.height - 8),
    });
  }, [position]);

  const create = async () => {
    const name = newName.trim();
    if (!name || !onCreate) return;
    const err = await onCreate(name);
    if (err) {
      setCreateError(err);
    } else {
      setNewName("");
      setCreateError(null);
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }} />
      <div
        ref={ref}
        className="fixed z-50 min-w-44 rounded-lg border border-border bg-card shadow-xl shadow-black/50 p-1"
        style={{ left: pos.x, top: pos.y }}
      >
        {!!actions?.length && (
          <>
            {actions.map((a) => (
              <button
                key={a.label}
                onClick={() => {
                  a.onClick();
                  onClose();
                }}
                className={cn(
                  "flex w-full items-center rounded-md px-2.5 py-1.5 text-sm text-left transition-colors hover:bg-muted",
                  a.danger && "text-danger",
                )}
              >
                {a.label}
              </button>
            ))}
            <div className="my-1 border-t border-border" />
          </>
        )}
        <div className="px-2.5 py-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
          {title ?? "Tag game"}
        </div>
        {tags.length === 0 && (
          <div className="px-2.5 py-1.5 text-sm text-muted-foreground">No tags yet</div>
        )}
        {tags.map((t) => {
          const state = checkState(t);
          return (
            <button
              key={t.id}
              onClick={() => onPick(t, state !== "all")}
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-sm text-left hover:bg-muted transition-colors"
            >
              <span
                className={cn(
                  "flex h-4 w-4 items-center justify-center rounded border border-border shrink-0",
                  state !== "none" && "bg-primary",
                )}
              >
                {state === "all" && <Check className="h-3 w-3" />}
                {state === "some" && <Minus className="h-3 w-3" />}
              </span>
              <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: tagColor(t.name, t.color) }} />
              {t.name}
            </button>
          );
        })}
        {onCreate && (
          <div className="mt-1 border-t border-border pt-1 px-1">
            <div className="flex items-center gap-1">
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void create()}
                placeholder="new tag"
                className="w-28 flex-1 rounded-md bg-muted px-2 py-1 text-sm outline-none placeholder:text-muted-foreground"
              />
              <button
                onClick={() => void create()}
                className="rounded-md p-1.5 hover:bg-muted text-muted-foreground hover:text-foreground"
                aria-label="Create tag"
              >
                <Plus className="h-4 w-4" />
              </button>
            </div>
            {createError && <div className="px-2 py-1 text-xs text-danger">{createError}</div>}
          </div>
        )}
      </div>
    </>
  );
}
