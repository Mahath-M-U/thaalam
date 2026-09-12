import type { ReactNode } from "react";
import { AskButton } from "./chat/AskButton";

interface Props {
  id: string;
  title: string;
  /**
   * Question the section's "Ask" button seeds. Omit to leave the heading
   * bare -- a section whose obvious question is already covered elsewhere
   * does not need its own.
   */
  ask?: string;
  children: ReactNode;
}

export function Section({ id, title, ask, children }: Props) {
  return (
    <section id={id} className="section">
      {ask ? (
        <div className="section-head">
          <h2 className="section-title">{title}</h2>
          <AskButton question={ask} label="Ask about this" />
        </div>
      ) : (
        <h2 className="section-title">{title}</h2>
      )}
      <div className="chart-grid">{children}</div>
    </section>
  );
}
