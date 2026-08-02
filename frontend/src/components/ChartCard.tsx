import type { ReactNode } from "react";

interface Props {
  title: string;
  description?: string;
  children: ReactNode;
  wide?: boolean;
}

export function ChartCard({ title, description, children, wide }: Props) {
  return (
    <article className={`chart-card${wide ? " wide" : ""}`}>
      <header className="chart-card-header">
        <h3>{title}</h3>
        {description ? <p>{description}</p> : null}
      </header>
      <div className="chart-body">{children}</div>
    </article>
  );
}
