/** Free-tier "peek" at Trends, shown on Today only when the user isn't
 * premium (design P7). A minimal 30-day FKDR line — no axes, no dots — with
 * a caption pointing at the full Trends page. Renders nothing until there
 * are at least two played days to draw a line between.
 */
import { Lock } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { Card, CardLabel } from "./shared";
import { prettyDateShort, ratio } from "../lib/format";
import { dailyRows, inRange } from "../lib/stats";
import { useData } from "../state/DataContext";

export function TrendPeekCard() {
  const { data } = useData();
  const daily = dailyRows(inRange(data?.games ?? [], "30d"));
  if (daily.length < 2) return null;

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <CardLabel>Last 30 days</CardLabel>
        <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
          <Lock className="h-3 w-3" /> Trends shows the full history
        </span>
      </div>
      <div className="mt-4 h-28 w-full min-w-0">
        <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
          <LineChart data={daily}>
            <XAxis dataKey="date" hide />
            <Tooltip
              contentStyle={{
                backgroundColor: "#18181b",
                border: "1px solid #27272a",
                borderRadius: "6px",
                fontSize: 12,
              }}
              labelFormatter={(d) => prettyDateShort(String(d))}
              formatter={(v) => [`${ratio(Number(v))} FKDR`, ""]}
            />
            <Line type="monotone" dataKey="fkdr" stroke="#fafafa" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
