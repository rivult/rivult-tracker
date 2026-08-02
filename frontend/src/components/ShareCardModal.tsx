/** Share card v1 (design P5) — renders a stat card as pure SVG (so the canvas
 * never taints) and downloads it as a PNG. No new deps, no network: every
 * number is already in the dashboard payload. The on-screen SVG IS the export
 * (serialized via XMLSerializer), so preview and file always match.
 */
import { useRef, useState } from "react";
import { Download, X } from "lucide-react";
import { prettyDateShort, ratio } from "../lib/format";
import { aggregate, inRange, latestSession } from "../lib/stats";
import { useData } from "../state/DataContext";

const W = 800;
const H = 420;
const SCALE = 2; // export at 2x for crisp text

type Scope = "session" | "7d";

function dateRange(dates: (string | null)[]): string {
  const present = dates.filter((d): d is string => Boolean(d)).sort();
  if (!present.length) return "";
  const from = present[0];
  const to = present[present.length - 1];
  return from === to ? prettyDateShort(from) : `${prettyDateShort(from)} – ${prettyDateShort(to)}`;
}

export function ShareCardModal({ scope, onClose }: { scope: Scope; onClose: () => void }) {
  const { data } = useData();
  const svgRef = useRef<SVGSVGElement>(null);
  const [error, setError] = useState<string | null>(null);

  const games = data?.games ?? [];
  const scoped = scope === "session" ? (latestSession(games)?.games ?? []) : inRange(games, "7d");
  const agg = aggregate(scoped);
  const player = data?.you || "Player";
  const scopeLabel = scope === "session" ? "This session" : "Last 7 days";
  const range = dateRange(scoped.map((g) => g.date));

  const download = () => {
    const el = svgRef.current;
    if (!el) return;
    try {
      const svg = new XMLSerializer().serializeToString(el);
      const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
      const img = new Image();
      img.onload = () => {
        try {
          const canvas = document.createElement("canvas");
          canvas.width = W * SCALE;
          canvas.height = H * SCALE;
          const ctx = canvas.getContext("2d");
          if (!ctx) {
            setError("Your browser blocked the canvas export.");
            return;
          }
          ctx.scale(SCALE, SCALE);
          ctx.drawImage(img, 0, 0, W, H);
          canvas.toBlob((blob) => {
            if (!blob) {
              setError("Could not encode the image.");
              return;
            }
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = `rivult-${scope}-${player}.png`;
            a.click();
            URL.revokeObjectURL(a.href);
          }, "image/png");
        } catch (e) {
          setError(e instanceof Error ? e.message : String(e));
        }
      };
      img.onerror = () => setError("Could not render the card image.");
      img.src = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const stats: [string, string][] = [
    ["W / L", `${agg.wins} / ${agg.losses}`],
    ["FINAL KILLS", String(agg.finalKills)],
    ["BEDS BROKEN", String(agg.bedsBroken)],
    ["W/L RATIO", ratio(agg.wlr)],
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        className="w-full max-w-2xl rounded-xl border border-border bg-card p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <div className="text-sm font-medium">Share card — {scopeLabel}</div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:text-foreground"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="overflow-hidden rounded-lg border border-border">
          <svg
            ref={svgRef}
            xmlns="http://www.w3.org/2000/svg"
            width={W}
            height={H}
            viewBox={`0 0 ${W} ${H}`}
            className="w-full"
          >
            <rect width={W} height={H} fill="#0e0f12" />
            <rect x={1} y={1} width={W - 2} height={H - 2} rx={16} fill="none" stroke="#27272a" strokeWidth={2} />

            <text x={48} y={64} fill="#fafafa" fontFamily="Inter, sans-serif" fontSize={26} fontWeight={800}>
              RIVULT
            </text>
            <text x={48} y={92} fill="#a1a1aa" fontFamily="Inter, sans-serif" fontSize={15}>
              Bedwars Tracker
            </text>
            <text x={W - 48} y={64} textAnchor="end" fill="#fafafa" fontFamily="Inter, sans-serif" fontSize={20} fontWeight={600}>
              {player}
            </text>
            <text x={W - 48} y={90} textAnchor="end" fill="#a1a1aa" fontFamily="Inter, sans-serif" fontSize={14}>
              {scopeLabel}
              {range ? ` · ${range}` : ""}
            </text>

            <text x={48} y={210} fill="#a1a1aa" fontFamily="Inter, sans-serif" fontSize={16} fontWeight={600} letterSpacing={2}>
              FKDR
            </text>
            <text x={44} y={296} fill="#22c55e" fontFamily="Inter, sans-serif" fontSize={104} fontWeight={800}>
              {ratio(agg.fkdr)}
            </text>

            {stats.map(([label, value], i) => {
              const x = 460 + (i % 2) * 170;
              const y = 200 + Math.floor(i / 2) * 96;
              return (
                <g key={label}>
                  <text x={x} y={y} fill="#a1a1aa" fontFamily="Inter, sans-serif" fontSize={13} letterSpacing={1}>
                    {label}
                  </text>
                  <text x={x} y={y + 34} fill="#fafafa" fontFamily="Inter, sans-serif" fontSize={30} fontWeight={700}>
                    {value}
                  </text>
                </g>
              );
            })}

            <text x={48} y={H - 36} fill="#52525b" fontFamily="Inter, sans-serif" fontSize={13}>
              {agg.games} games · green = good, red = bad
            </text>
          </svg>
        </div>

        <div className="mt-4 flex items-center justify-end gap-3">
          {error && <span className="mr-auto text-sm text-danger">{error}</span>}
          <button
            onClick={onClose}
            className="rounded-md border border-border bg-card px-3 py-2 text-sm hover:bg-muted"
          >
            Close
          </button>
          <button
            onClick={download}
            className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/80"
          >
            <Download className="h-4 w-4" /> Download PNG
          </button>
        </div>
      </div>
    </div>
  );
}
