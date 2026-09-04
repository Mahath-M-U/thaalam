import type { ReactNode } from "react";

interface Props {
  id: string;
  title: string;
  children: ReactNode;
}

export function Section({ id, title, children }: Props) {
  return (
    <section id={id} className="section">
      <h2 className="section-title">{title}</h2>
      <div className="chart-grid">{children}</div>
    </section>
  );
}
