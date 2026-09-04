import type { DerivedRead, ReadGroup } from "../types";
import { AMBER } from "../chartTheme";

const GROUPS: { id: ReadGroup; label: string }[] = [
  { id: "sleep", label: "Sleep" },
  { id: "load", label: "Load" },
  { id: "rhythm", label: "Rhythm & Habit" },
];

interface Props {
  reads: DerivedRead[];
  onOpen: (id: string) => void;
}

export function ReadsTable({ reads, onOpen }: Props) {
  return (
    <section id="reads" className="section reads-section">
      <h2 className="section-title">All eleven reads</h2>
      {GROUPS.map((group) => {
        const rows = reads.filter((read) => read.group === group.id);
        if (rows.length === 0) return null;
        return (
          <div key={group.id} className="reads-group">
            <div className="reads-group-kicker">{group.label}</div>
            <ul className="reads-list">
              {rows.map((read) => (
                <li key={read.id}>
                  <button type="button" className="read-row" onClick={() => onOpen(read.id)}>
                    <div className="read-row-copy">
                      <h3>{read.title}</h3>
                      <p>{read.finding}</p>
                    </div>
                    <div className="read-row-viz">
                      {read.calibrating || read.sparkline.length < 2 ? (
                        <span className="read-progress">
                          {read.progress ?? 0}/{read.progress_needed ?? 0}
                        </span>
                      ) : (
                        <Sparkline values={read.sparkline} favourable={read.favourable !== false} />
                      )}
                      <span className="read-chevron" aria-hidden="true">
                        ›
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

export function Sparkline({
  values,
  favourable,
  width = 88,
  height = 28,
}: {
  values: number[];
  favourable: boolean;
  width?: number;
  height?: number;
}) {
  const nums = values.filter((v) => Number.isFinite(v));
  if (nums.length < 2) return null;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const step = (width - 4) / (nums.length - 1);
  const points = nums
    .map((v, i) => {
      const x = 2 + i * step;
      const y = height - 3 - ((v - min) / span) * (height - 6);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg className="sparkline" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline
        fill="none"
        stroke={favourable ? AMBER : "#8A8A8A"}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        points={points}
      />
    </svg>
  );
}
