import { useChat } from "../../chat/ChatProvider";

/**
 * "Ask about this" — the assistant's entry point on an individual card,
 * section or deep dive.
 *
 * Two behaviours, because both are wanted in different places:
 * `send` fires the question immediately (right for a specific card, where the
 * question is obvious), while the default drops it into the input for the
 * user to edit first (right for a whole section, where they may want to
 * narrow it).
 *
 * Renders nothing when the assistant is not configured, so every one of these
 * disappears together on an install without an API key.
 */
interface Props {
  /** The question to ask, written as the user would ask it. */
  question: string;
  /** Button text. Kept short; these sit next to headings. */
  label?: string;
  /** Ask straight away instead of prefilling the input. */
  send?: boolean;
  className?: string;
}

export function AskButton({ question, label = "Ask", send = false, className }: Props) {
  const { enabled, ask, openDock } = useChat();
  if (!enabled) return null;

  return (
    <button
      type="button"
      className={className ?? "ask-btn"}
      title={question}
      onClick={() => (send ? ask(question) : openDock(question))}
    >
      <span aria-hidden="true">✦</span> {label}
    </button>
  );
}
