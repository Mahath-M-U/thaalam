import { useEffect, useRef, type FormEvent, type KeyboardEvent } from "react";
import { useChat } from "../../chat/ChatProvider";

/**
 * The assistant, reachable from every screen.
 *
 * A launcher button that expands into a panel: a sheet on mobile, a docked
 * card bottom-right on desktop. It renders nothing at all when the server
 * reports no API key, so an install without one shows no dead affordance.
 */

/** What each page key is called in the panel's header. */
const PAGE_LABEL: Record<string, string> = {
  overview: "Overview",
  insights: "Insights",
  recovery: "Recovery",
  strain: "Strain",
  sleep: "Sleep",
  workouts: "Workouts",
  reads: "Reads",
  read: "this read",
  runway: "Runway",
  today: "Today",
  admin: "Administration",
};

export function ChatDock() {
  const {
    enabled,
    open,
    page,
    entries,
    pending,
    suggestions,
    draft,
    setDraft,
    openDock,
    closeDock,
    ask,
    clear,
  } = useChat();

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // Keep the newest turn in view as answers arrive.
  useEffect(() => {
    if (!open) return;
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [open, entries, pending]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Escape closes the panel, which is what a dialog-shaped thing should do.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") closeDock();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, closeDock]);

  if (!enabled) return null;

  if (!open) {
    return (
      <button
        type="button"
        className="chat-launcher"
        onClick={() => openDock()}
        aria-label="Ask about this page"
      >
        <span className="chat-launcher-mark" aria-hidden="true">
          ✦
        </span>
        <span className="chat-launcher-text">Ask</span>
      </button>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (pending) return;
    ask(draft);
  };

  // Enter sends, Shift+Enter makes a newline -- the convention every other
  // chat input uses, so it needs no explaining.
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!pending) ask(draft);
    }
  };

  const where = PAGE_LABEL[page] ?? "your data";

  return (
    <div className="chat-dock" role="dialog" aria-label="Thaalam assistant" aria-modal="false">
      <header className="chat-dock-head">
        <div>
          <strong>Ask Thaalam</strong>
          <small>Answering from {where}</small>
        </div>
        <div className="chat-dock-head-actions">
          {entries.length > 0 ? (
            <button type="button" className="chat-icon-btn" onClick={clear} title="New conversation">
              Clear
            </button>
          ) : null}
          <button
            type="button"
            className="chat-icon-btn"
            onClick={closeDock}
            aria-label="Close the assistant"
          >
            ✕
          </button>
        </div>
      </header>

      <div className="chat-scroll" ref={scrollRef}>
        {entries.length === 0 ? (
          <div className="chat-empty">
            <p>
              Ask about what is on this page. Answers come from your own synced
              data and the baselines computed from it.
            </p>
            <p className="chat-disclaimer">
              Descriptive analytics on your own history — not medical advice.
            </p>
          </div>
        ) : null}

        {entries.map((entry) => (
          <div
            key={entry.id}
            className={`chat-turn ${entry.role}${entry.failed ? " failed" : ""}`}
          >
            <ChatBody text={entry.content} />
            {entry.unready ? (
              <p className="chat-note">
                No synced history yet, so this is general guidance rather than
                your own numbers.
              </p>
            ) : null}
            {entry.groundedOn && entry.groundedOn.length > 0 ? (
              <p className="chat-grounding">Based on {entry.groundedOn.join(", ")}</p>
            ) : null}
          </div>
        ))}

        {pending ? (
          <div className="chat-turn assistant pending" aria-live="polite">
            <span className="chat-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            <span className="chat-pending-text">Reading your data…</span>
          </div>
        ) : null}
      </div>

      {entries.length === 0 && suggestions.length > 0 ? (
        <div className="chat-suggestions">
          {suggestions.map((question) => (
            <button
              key={question}
              type="button"
              className="chat-suggestion"
              onClick={() => ask(question)}
              disabled={pending}
            >
              {question}
            </button>
          ))}
        </div>
      ) : null}

      <form className="chat-input-row" onSubmit={submit}>
        <textarea
          ref={inputRef}
          className="chat-input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={`Ask about ${where.toLowerCase()}…`}
          rows={1}
          maxLength={2000}
        />
        <button type="submit" className="btn chat-send" disabled={pending || !draft.trim()}>
          {pending ? "…" : "Send"}
        </button>
      </form>
    </div>
  );
}

/**
 * Render an answer's text.
 *
 * The model is told to reply in plain text with '-' bullets, so this only
 * needs to honour paragraphs and those bullets. Deliberately not a markdown
 * renderer: the text is model output, and `textContent` on every line is what
 * guarantees it cannot inject markup into the dashboard.
 */
function ChatBody({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <>
      {blocks.map((block, blockIndex) => {
        const lines = block.split("\n").filter((line) => line.trim());
        const bullets = lines.filter((line) => /^\s*[-*•]\s+/.test(line));

        if (bullets.length === lines.length && lines.length > 0) {
          return (
            <ul key={blockIndex} className="chat-bullets">
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>{line.replace(/^\s*[-*•]\s+/, "")}</li>
              ))}
            </ul>
          );
        }
        return <p key={blockIndex}>{lines.join(" ")}</p>;
      })}
    </>
  );
}
