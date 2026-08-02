import { tagColor } from "../lib/format";

export function TagBadge({ name, color }: { name: string; color?: string | null }) {
  const c = tagColor(name, color ?? null);
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-[11px] leading-4 text-muted-foreground border border-border/60 bg-muted/40 whitespace-nowrap"
      style={{ borderColor: `${c}55` }}
    >
      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: c }} />
      {name}
    </span>
  );
}
