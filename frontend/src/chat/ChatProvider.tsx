import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, api } from "../api";
import type { ChatPage, ChatTurn } from "../types";

/**
 * Conversation state for the assistant, held above the dock.
 *
 * It lives here rather than inside `ChatDock` for one reason: "Ask about
 * this" buttons are scattered across sections, deep dives and cards, and all
 * of them need to open the dock with a question already in it. A provider
 * gives every one of them `ask()` without threading callbacks through the
 * component tree.
 *
 * The page the dock is open on is pushed in from `App`, which reads it from
 * the URL, and travels with each question -- that is what makes an answer
 * about what the user is actually looking at.
 */

export interface ChatEntry {
  id: number;
  role: "user" | "assistant";
  content: string;
  /** What the answer was grounded in; assistant entries only. */
  groundedOn?: string[];
  model?: string;
  /** True when the server answered with no synced history to work from. */
  unready?: boolean;
  /** Set instead of content when the request failed. */
  failed?: boolean;
}

interface ChatContextValue {
  /** False until the server confirms a key is configured; hides the dock. */
  enabled: boolean;
  open: boolean;
  page: ChatPage;
  entries: ChatEntry[];
  pending: boolean;
  error: string | null;
  suggestions: string[];
  draft: string;
  setDraft: (value: string) => void;
  openDock: (seed?: string) => void;
  closeDock: () => void;
  ask: (question: string) => void;
  clear: () => void;
}

const ChatCtx = createContext<ChatContextValue | null>(null);

export function useChat(): ChatContextValue {
  const ctx = useContext(ChatCtx);
  if (!ctx) throw new Error("useChat must be used inside <ChatProvider>");
  return ctx;
}

/** How many prior turns to send. The server trims too; this saves the bytes. */
const HISTORY_LIMIT = 8;

interface Props {
  page: ChatPage;
  readId?: string | null;
  rangeDays?: number | null;
  children: ReactNode;
}

export function ChatProvider({ page, readId = null, rangeDays = null, children }: Props) {
  const [enabled, setEnabled] = useState(false);
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [draft, setDraft] = useState("");

  // `ask` is handed to buttons all over the tree and must not be rebuilt
  // every time the route changes, so the request reads the live page from a
  // ref instead of closing over it.
  const scope = useRef({ page, readId, rangeDays });
  scope.current = { page, readId, rangeDays };

  const nextId = useRef(1);
  const inFlight = useRef<AbortController | null>(null);
  // Mirrors `entries` so `ask` can assemble the history it sends without
  // reading state inside a setState updater -- StrictMode runs updaters
  // twice, which would fire the request twice and bill two free-tier calls.
  const entriesRef = useRef<ChatEntry[]>([]);

  const commit = useCallback((next: ChatEntry[]) => {
    entriesRef.current = next;
    setEntries(next);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .chatStatus()
      .then((status) => {
        if (!cancelled) setEnabled(status.enabled);
      })
      // A viewer who cannot reach the status route simply gets no dock.
      .catch(() => {
        if (!cancelled) setEnabled(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Starter questions follow the page, so the dock always offers something
  // worth clicking wherever it is opened.
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    api
      .chatSuggestions(page)
      .then((res) => {
        if (!cancelled) setSuggestions(res.suggestions);
      })
      .catch(() => {
        if (!cancelled) setSuggestions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, page]);

  useEffect(() => () => inFlight.current?.abort(), []);

  const ask = useCallback(
    (question: string) => {
      const text = question.trim();
      if (!text) return;

      setOpen(true);
      setDraft("");
      setError(null);

      // Abandon a still-running question rather than interleaving two answers.
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;

      const history = [
        ...entriesRef.current,
        { id: nextId.current++, role: "user" as const, content: text },
      ];
      commit(history);

      const turns: ChatTurn[] = history
        .filter((entry) => !entry.failed)
        .slice(-HISTORY_LIMIT)
        .map((entry) => ({ role: entry.role, content: entry.content }));

      setPending(true);
      const { page: askedOn, readId: openRead, rangeDays: days } = scope.current;
      api
        .chatSend(
          {
            messages: turns,
            page: askedOn,
            read_id: askedOn === "read" ? openRead : null,
            range_days: days,
          },
          controller.signal,
        )
        .then((res) => {
          if (controller.signal.aborted) return;
          commit([
            ...entriesRef.current,
            {
              id: nextId.current++,
              role: "assistant",
              content: res.reply,
              groundedOn: res.grounded_on,
              model: res.model,
              unready: !res.ready,
            },
          ]);
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          // 429 is the expected failure here, not an exceptional one: the
          // free tier is rationed, so the message says to wait rather than
          // implying something is broken.
          const message =
            err instanceof ApiError
              ? err.message
              : "Could not reach the assistant. Check your connection and try again.";
          setError(message);
          commit([
            ...entriesRef.current,
            { id: nextId.current++, role: "assistant", content: message, failed: true },
          ]);
        })
        .finally(() => {
          if (!controller.signal.aborted) setPending(false);
        });
    },
    [commit],
  );

  const openDock = useCallback((seed?: string) => {
    setOpen(true);
    if (seed) setDraft(seed);
  }, []);

  const closeDock = useCallback(() => {
    setOpen(false);
  }, []);

  const clear = useCallback(() => {
    inFlight.current?.abort();
    commit([]);
    setError(null);
    setPending(false);
  }, [commit]);

  const value = useMemo<ChatContextValue>(
    () => ({
      enabled,
      open,
      page,
      entries,
      pending,
      error,
      suggestions,
      draft,
      setDraft,
      openDock,
      closeDock,
      ask,
      clear,
    }),
    [enabled, open, page, entries, pending, error, suggestions, draft, openDock, closeDock, ask, clear],
  );

  return <ChatCtx.Provider value={value}>{children}</ChatCtx.Provider>;
}
