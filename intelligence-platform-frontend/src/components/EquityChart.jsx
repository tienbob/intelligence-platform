import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from 'recharts';

const fmtMoney = (v) =>
  '$' + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });

const fmtDate = (d) =>
  new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

function EquityTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-lg border border-outline-variant bg-surface-container-high px-3 py-2 text-xs shadow-lg">
      <p className="text-on-surface-variant mb-1">{fmtDate(point.date)}</p>
      <p className="font-semibold data-font text-tertiary">{fmtMoney(point.value)}</p>
      {point.pl != null && (
        <p className={`data-font ${point.pl >= 0 ? 'text-tertiary' : 'text-error'}`}>
          {point.pl >= 0 ? '+' : ''}
          {(point.pl * 100).toFixed(2)}% vs. start
        </p>
      )}
    </div>
  );
}

/**
 * Interactive equity-curve area chart for a backtest run.
 *
 * @param {Array<{date: string, value: number}>} points - equity curve points
 * @param {number} initialCapital - drawn as a dashed baseline
 */
export default function EquityChart({ points = [], initialCapital = null }) {
  if (!points || points.length < 2) return null;

  const data = points.map((p) => ({
    ...p,
    pl: initialCapital ? p.value / initialCapital - 1 : null,
  }));

  return (
    <div className="h-64 w-full" data-testid="equity-chart">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 10, right: 12, bottom: 0, left: 4 }}>
          <defs>
            <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#4edea3" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#4edea3" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#273647" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={fmtDate}
            tick={{ fill: '#8b98ad', fontSize: 11 }}
            axisLine={{ stroke: '#273647' }}
            tickLine={false}
            minTickGap={48}
          />
          <YAxis
            tickFormatter={fmtMoney}
            tick={{ fill: '#8b98ad', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={70}
            domain={['auto', 'auto']}
          />
          <Tooltip content={<EquityTooltip />} cursor={{ stroke: '#adc6ff', strokeDasharray: '4 4' }} />
          {initialCapital != null && (
            <ReferenceLine
              y={initialCapital}
              stroke="#8b98ad"
              strokeDasharray="6 4"
              label={{
                value: 'Start',
                position: 'insideBottomLeft',
                fill: '#8b98ad',
                fontSize: 10,
              }}
            />
          )}
          <Area
            type="monotone"
            dataKey="value"
            stroke="#4edea3"
            strokeWidth={2}
            fill="url(#equityFill)"
            dot={false}
            activeDot={{ r: 4, fill: '#4edea3', stroke: '#051424' }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}