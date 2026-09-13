import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { useChat, type ChatEntry } from "../../chat/ChatProvider";

/**
 * The assistant, reachable from every screen.
 *
 * A launcher button that expands into a panel: a sheet on mobile, a docked
 * card bottom-right on desktop. It renders nothing at all when the server
 * reports no API key, so an install without one shows no dead affordance.
 *
 * The layout follows the convention a chat assistant has earned: the question
 * is a short bubble on the right, the answer is full-width prose on the left
 * under a mark, and the answer is written into the transcript as it streams
 * rather than appearing all at once when it is finished. A caret marks the
 * live edge, the send button turns into a stop button while it writes, and
 * stopping keeps what was said.
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

/** How far from the bottom still counts as "following the answer". */
const FOLLOW_THRESHOLD_PX = 56;

/** Tallest the composer grows before it scrolls instead. */
const MAX_COMPOSER_PX = 168;

export function ChatDock() {
  const {
    enabled,
    open,
    page,
    entries,
    pending,
    streaming,
    suggestions,
    draft,
    lastQuestion,
    setDraft,
    openDock,
    closeDock,
    ask,
    stop,
    retry,
    clear,
  } = useChat();

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [following, setFollowing] = useState(true);
  const [expanded, setExpanded] = useState(false);

  const busy = pending || streaming;

  // "auto" here means instant: the transcript has no CSS `scroll-behavior`, so
  // following a streaming answer never animates. Only the jump button, which
  // moves a long way on purpose, asks for a smooth scroll.
  const scrollToEnd = useCallback((smooth = false) => {
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTo({ top: node.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }, []);

  // Follow the answer as it is written -- but only while the user is at the
  // bottom. Someone who has scrolled up to re-read an earlier turn must not
  // be dragged back down by every token that arrives.
  useLayoutEffect(() => {
    if (!open || !following) return;
    scrollToEnd();
  }, [open, following, entries, pending, scrollToEnd]);

  const onScroll = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
    setFollowing(distance <= FOLLOW_THRESHOLD_PX);
  }, []);

  // Grow the composer with its content instead of scrolling a one-line box.
  useLayoutEffect(() => {
    const node = inputRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, MAX_COMPOSER_PX)}px`;
  }, [draft, open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Escape stops a running answer first, and only closes the panel once
  // there is nothing to interrupt -- otherwise the reflex to cancel also
  // throws away the answer you were reading.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (busy) stop();
      else closeDock();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, stop, closeDock]);

  if (!enabled) return null;

  const where = PAGE_LABEL[page] ?? "your data";

  if (!open) {
    return (
      <button
        type="button"
        className="chat-launcher"
        onClick={() => openDock()}
        aria-label={`Ask about ${where}`}
      >
        <SparkMark />
        <span className="chat-launcher-text">Ask</span>
      </button>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    ask(draft);
  };

  // Enter sends, Shift+Enter makes a newline -- the convention every other
  // chat input uses, so it needs no explaining.
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!busy) ask(draft);
    }
  };

  const empty = entries.length === 0;
  const lastId = entries.length ? entries[entries.length - 1].id : -1;

  return (
    <div
      className={`chat-dock${expanded ? " expanded" : ""}`}
      role="dialog"
      aria-label="Thaalam assistant"
      aria-modal="false"
    >
      <header className="chat-dock-head">
        <div className="chat-dock-title">
          <SparkMark />
          <div>
            <strong>Thaalam</strong>
            <small>{empty ? `Ready on ${where}` : `Answering from ${where}`}</small>
          </div>
        </div>
        <div className="chat-dock-head-actions">
          {!empty ? (
            <button
              type="button"
              className="chat-icon-btn"
              onClick={clear}
              title="New conversation"
              aria-label="New conversation"
            >
              <IconNew />
            </button>
          ) : null}
          <button
            type="button"
            className="chat-icon-btn chat-expand-btn"
            onClick={() => setExpanded((value) => !value)}
            title={expanded ? "Shrink the panel" : "Expand the panel"}
            aria-label={expanded ? "Shrink the panel" : "Expand the panel"}
            aria-pressed={expanded}
          >
            {expanded ? <IconShrink /> : <IconExpand />}
          </button>
          <button
            type="button"
            className="chat-icon-btn"
            onClick={closeDock}
            title="Close"
            aria-label="Close the assistant"
          >
            <IconClose />
          </button>
        </div>
      </header>

      <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
        {empty ? (
          <div className="chat-empty">
            <SparkMark className="chat-empty-mark" />
            <h3>Ask about {where.toLowerCase()}</h3>
            <p>
              Answers come from your own synced data and the baselines computed
              from it — never from figures your browser happens to be holding.
            </p>
          </div>
        ) : null}

        {entries.map((entry) => (
          <Turn
            key={entry.id}
            entry={entry}
            canRetry={entry.id === lastId && !busy && Boolean(lastQuestion)}
            onRetry={retry}
          />
        ))}

        {pending ? (
          <div className="chat-turn assistant">
            <SparkMark className="chat-turn-mark" />
            <div className="chat-turn-body chat-thinking">
              <span className="chat-dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              <span className="chat-pending-text">Reading your data…</span>
            </div>
          </div>
        ) : null}

        {empty ? null : <p className="chat-disclaimer">Descriptive analytics, not medical advice.</p>}
      </div>

      <span className="visually-hidden" aria-live="polite">
        {pending ? "Reading your data" : streaming ? "Answering" : ""}
      </span>

      {!following && !empty ? (
        <button
          type="button"
          className="chat-jump"
          onClick={() => {
            setFollowing(true);
            scrollToEnd(true);
          }}
        >
          <IconDown /> Jump to latest
        </button>
      ) : null}

      {empty && suggestions.length > 0 ? (
        <div className="chat-suggestions">
          {suggestions.map((question) => (
            <button
              key={question}
              type="button"
              className="chat-suggestion"
              onClick={() => ask(question)}
              disabled={busy}
            >
              <span>{question}</span>
              <IconArrow />
            </button>
          ))}
        </div>
      ) : null}

      <form className="chat-input-row" onSubmit={submit}>
        <div className="chat-composer">
          <textarea
            ref={inputRef}
            className="chat-input"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder={`Ask about ${where.toLowerCase()}…`}
            rows={1}
            maxLength={2000}
            aria-label={`Ask about ${where}`}
          />
          {busy ? (
            <button
              type="button"
              className="chat-send stop"
              onClick={stop}
              title="Stop answering"
              aria-label="Stop answering"
            >
              <IconStop />
            </button>
          ) : (
            <button
              type="submit"
              className="chat-send"
              disabled={!draft.trim()}
              title="Send"
              aria-label="Send"
            >
              <IconSend />
            </button>
          )}
        </div>
        <p className="chat-hint">
          <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line
        </p>
      </form>
    </div>
  );
}

/**
 * One turn of the conversation.
 *
 * The question is a bubble because it is short and the user wrote it; the
 * answer is prose under a mark because it is long and worth reading as a
 * block. The footnotes hang below the answer rather than inside it, so they
 * cannot be mistaken for something the model said.
 */
function Turn({
  entry,
  canRetry,
  onRetry,
}: {
  entry: ChatEntry;
  canRetry: boolean;
  onRetry: () => void;
}) {
  if (entry.role === "user") {
    return (
      <div className="chat-turn user">
        <div className="chat-turn-body">{entry.content}</div>
      </div>
    );
  }

  // An answer that has been claimed but has no text yet is covered by the
  // "reading your data" row; rendering an empty bubble under it reads as a
  // glitch.
  if (!entry.content && entry.streaming) return null;

  return (
    <div className={`chat-turn assistant${entry.failed ? " failed" : ""}`}>
      <SparkMark className="chat-turn-mark" />
      <div className="chat-turn-body" aria-busy={entry.streaming || undefined}>
        <ChatBody text={entry.content} caret={entry.streaming} />

        {/* Footnotes wait for the end. Hanging them under a sentence that is
            still being written moves the text the user is reading. */}
        {entry.streaming ? null : (
          <>
            {entry.unready ? (
              <p className="chat-note">
                No synced history yet, so this is general guidance rather than
                your own numbers.
              </p>
            ) : null}
            {entry.truncated ? <p className="chat-note">{entry.truncated}</p> : null}
            {entry.groundedOn && entry.groundedOn.length > 0 ? (
              <p className="chat-grounding">Based on {entry.groundedOn.join(", ")}</p>
            ) : null}
          </>
        )}

        {!entry.streaming && entry.content ? (
          <div className="chat-turn-actions">
            {!entry.failed ? <CopyButton text={entry.content} /> : null}
            {canRetry ? (
              <button type="button" className="chat-mini-btn" onClick={onRetry}>
                <IconRetry /> {entry.failed ? "Try again" : "Regenerate"}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(timer);
  }, [copied]);

  return (
    <button
      type="button"
      className="chat-mini-btn"
      onClick={() => {
        // `clipboard` is unavailable over plain HTTP on a non-localhost
        // origin, which a self-hosted install can easily be.
        navigator.clipboard?.writeText(text).then(
          () => setCopied(true),
          () => setCopied(false),
        );
      }}
    >
      {copied ? <IconCheck /> : <IconCopy />} {copied ? "Copied" : "Copy"}
    </button>
  );
}

/**
 * Render an answer's text.
 *
 * The model is told to reply in plain text with '-' bullets, so this handles
 * paragraphs, bullet and numbered lists, and the `**bold**` / `` `code` ``
 * emphasis models emit anyway. Deliberately not a markdown renderer: every
 * piece of this ends up as a React text node, which is what guarantees model
 * output cannot inject markup into the dashboard.
 *
 * It also has to cope with half a sentence, since it renders text that is
 * still arriving.
 */
type Block = { kind: "p" | "ul" | "ol"; lines: string[] };

function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let current: Block | null = null;

  const open = (kind: Block["kind"]): Block => {
    if (!current || current.kind !== kind) {
      current = { kind, lines: [] };
      blocks.push(current);
    }
    return current;
  };

  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) {
      current = null;
      continue;
    }
    // The text after the marker is optional so that a bullet whose first word
    // has not arrived yet is already a list item. Without that, a streamed
    // "- " spends a frame on screen as a literal dash in a paragraph.
    const bullet = /^[-*•](?:\s+(.*))?$/.exec(line);
    if (bullet) {
      open("ul").lines.push(bullet[1] ?? "");
      continue;
    }
    const numbered = /^\d+[.)](?:\s+(.*))?$/.exec(line);
    if (numbered) {
      open("ol").lines.push(numbered[1] ?? "");
      continue;
    }
    open("p").lines.push(line);
  }
  return blocks;
}

/** `**bold**`, `*italic*` and `` `code` ``, as elements rather than markup. */
const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\n]+\*|_[^_\n]+_)/g;

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  return text.split(INLINE).map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    if (
      part.length > 2 &&
      ((part.startsWith("*") && part.endsWith("*")) || (part.startsWith("_") && part.endsWith("_")))
    ) {
      return <em key={key}>{part.slice(1, -1)}</em>;
    }
    return part;
  });
}

/**
 * `caret` marks the live edge of a streaming answer. It is rendered *inside*
 * the last element rather than after the whole body, so it sits at the end of
 * the sentence being written instead of dropping onto a line of its own.
 */
function ChatBody({ text, caret = false }: { text: string; caret?: boolean }) {
  const blocks = parseBlocks(text);
  const lastBlock = blocks.length - 1;
  const cursor = <span className="chat-caret" aria-hidden="true" />;

  // Nothing to hang the caret off yet: the first token has not landed.
  if (caret && blocks.length === 0) return <p>{cursor}</p>;

  return (
    <>
      {blocks.map((block, index) => {
        const live = caret && index === lastBlock;
        if (block.kind === "p") {
          return (
            <p key={index}>
              {renderInline(block.lines.join(" "), String(index))}
              {live ? cursor : null}
            </p>
          );
        }
        const Tag = block.kind === "ul" ? "ul" : "ol";
        const lastLine = block.lines.length - 1;
        return (
          <Tag key={index} className="chat-bullets">
            {block.lines.map((line, lineIndex) => (
              <li key={lineIndex}>
                {renderInline(line, `${index}-${lineIndex}`)}
                {live && lineIndex === lastLine ? cursor : null}
              </li>
            ))}
          </Tag>
        );
      })}
    </>
  );
}

/* --------------------------------------------------------------------------
   Icons. Inline so they inherit `currentColor` and cost no extra request.
   -------------------------------------------------------------------------- */

function SparkMark({ className }: { className?: string }) {
  return (
    <span className={className ?? "chat-launcher-mark"} aria-hidden="true">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
        <path d="M12 2.5l1.9 5.9a3 3 0 0 0 1.9 1.9l5.9 1.9-5.9 1.9a3 3 0 0 0-1.9 1.9L12 21.9l-1.9-5.9a3 3 0 0 0-1.9-1.9L2.3 12.2l5.9-1.9a3 3 0 0 0 1.9-1.9L12 2.5z" />
      </svg>
    </span>
  );
}

const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function IconSend() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" {...stroke} aria-hidden="true">
      <path d="M12 19V5M6 11l6-6 6 6" />
    </svg>
  );
}

function IconStop() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" />
    </svg>
  );
}

function IconClose() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" {...stroke} aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

function IconNew() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" {...stroke} aria-hidden="true">
      <path d="M4 5.5h10M4 12h7M4 18.5h7M17.5 12v8M13.5 16h8" />
    </svg>
  );
}

function IconExpand() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" {...stroke} aria-hidden="true">
      <path d="M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7" />
    </svg>
  );
}

function IconShrink() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" {...stroke} aria-hidden="true">
      <path d="M20 10h-6V4M14 10l6-6M4 14h6v6M10 14l-6 6" />
    </svg>
  );
}

function IconCopy() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" {...stroke} aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h8" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" {...stroke} aria-hidden="true">
      <path d="M5 12.5l4.5 4.5L19 7" />
    </svg>
  );
}

function IconRetry() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" {...stroke} aria-hidden="true">
      <path d="M20 11a8 8 0 1 0-2.3 5.7" />
      <path d="M20 5v6h-6" />
    </svg>
  );
}

function IconDown() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" {...stroke} aria-hidden="true">
      <path d="M12 5v14M6 13l6 6 6-6" />
    </svg>
  );
}

function IconArrow() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" {...stroke} aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}
