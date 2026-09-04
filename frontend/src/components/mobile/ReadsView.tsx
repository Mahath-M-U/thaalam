import type { DerivedRead } from "../../types";
import { ReadsTable } from "../ReadsTable";

interface Props {
  reads: DerivedRead[];
  onOpen: (id: string) => void;
}

export function ReadsView({ reads, onOpen }: Props) {
  if (reads.length === 0) {
    return (
      <div className="state-panel">
        <p>Calibrating your eleven reads from your own nights.</p>
      </div>
    );
  }

  return (
    <div className="mobile-reads">
      <ReadsTable reads={reads} onOpen={onOpen} heading={null} />
    </div>
  );
}
