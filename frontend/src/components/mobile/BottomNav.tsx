import type { TabId } from "../../types";

const TABS: { id: TabId; label: string; home?: boolean }[] = [
  { id: "today", label: "Today", home: true },
  { id: "sleep", label: "Sleep" },
  { id: "load", label: "Load" },
  { id: "rhythm", label: "Rhythm" },
  { id: "whoop", label: "WHOOP" },
];

interface Props {
  tab: TabId;
  onTab: (tab: TabId) => void;
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

function TabIcon({ id }: { id: TabId }) {
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
  if (id === "sleep") {
    // Crescent: the sleep group.
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M19.4 14.6A7.6 7.6 0 0 1 9.4 4.6a7.6 7.6 0 1 0 10 10Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (id === "load") {
    // Rising trace: the load group.
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M4 16.6 9 11l3.4 3.4L20 6.9"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M15.4 6.9H20v4.6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (id === "rhythm") {
    // Clock: the rhythm group.
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="7.25" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M12 8.2v4.1l2.7 1.6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  // Layers: the raw WHOOP series kept underneath everything else.
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M12 4.4 4.6 8.2 12 12l7.4-3.8L12 4.4Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path d="m4.6 12.6 7.4 3.8 7.4-3.8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}
