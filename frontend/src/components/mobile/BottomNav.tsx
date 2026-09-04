import type { MobileTab } from "../../types";

const TABS: { id: MobileTab; label: string; home?: boolean }[] = [
  { id: "today", label: "Today", home: true },
  { id: "reads", label: "Reads" },
  { id: "runway", label: "Runway" },
];

interface Props {
  tab: MobileTab;
  onTab: (tab: MobileTab) => void;
  hidden?: boolean;
}

export function BottomNav({ tab, onTab, hidden = false }: Props) {
  return (
    <nav
      className={`bottom-nav${hidden ? " is-hidden" : ""}`}
      aria-label="Mobile"
      aria-hidden={hidden || undefined}
      inert={hidden || undefined}
    >
      {TABS.map((item) => (
        <button
          key={item.id}
          type="button"
          className={`${tab === item.id ? "active" : ""}${item.home ? " nav-home" : ""}`.trim()}
          onClick={() => onTab(item.id)}
        >
          <TabIcon id={item.id} />
          {item.label}
        </button>
      ))}
    </nav>
  );
}

function TabIcon({ id }: { id: MobileTab }) {
  if (id === "today") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M4.5 11.2 12 4.8l7.5 6.4v8.1a1.2 1.2 0 0 1-1.2 1.2h-4.1v-5.1h-4.4v5.1H5.7a1.2 1.2 0 0 1-1.2-1.2v-8.1Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (id === "reads") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M7 5.5h10.5A1.5 1.5 0 0 1 19 7v12.2L12 16.4 5 19.2V7A1.5 1.5 0 0 1 6.5 5.5H7Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="7.25" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 8.2v4.1l2.7 1.6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
