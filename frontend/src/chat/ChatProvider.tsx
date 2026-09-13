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
import { ApiError, StreamUnsupported, api } from "../api";
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
 *
 * Answers stream. The assistant entry is created empty the moment a question
 * is sent and filled in as tokens arrive, so the two states the UI cares
 * about are distinct: `pending` is "asked, nothing back yet", `streaming` is
 * "words are appearing". Stopping keeps whatever arrived rather than throwing
 * a half-useful answer away.
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
  /** True while tokens are still arriving into this entry. */
  streaming?: boolean;
  /** Why an answer stopped early, when it still said something useful first. */
  truncated?: string;
}

interface ChatContextValue {
  /** False until the server confirms a key is configured; hides the dock. */
  enabled: boolean;
  open: boolean;
  page: ChatPage;
  entries: ChatEntry[];
  /** A question is out and nothing has come back yet. */
  pending: boolean;
  /** An answer is arriving, token by token. */
  streaming: boolean;
  error: string | null;
  suggestions: string[];
  draft: string;
  /** The last question asked, so it can be sent again after a failure. */
  lastQuestion: string | null;
  setDraft: (value: string) => void;
  openDock: (seed?: string) => void;
  closeDock: () => void;
  ask: (question: string) => void;
  /** Cut the answer short, keeping what has arrived. */
  stop: () => void;
  /** Ask the last question again, dropping the answer it produced. */
  retry: () => void;
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
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);

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

  /** Rewrite one entry in place, leaving the rest of the conversation alone. */
  const patch = useCallback(
    (id: number, change: (entry: ChatEntry) => ChatEntry) => {
      commit(entriesRef.current.map((entry) => (entry.id === id ? change(entry) : entry)));
    },
    [commit],
  );

  /**
   * Settle any answer still marked live.
   *
   * Both stopping and asking something new abandon a running answer, and
   * neither can leave the entry claiming to be streaming -- the caret would
   * blink on it for the rest of the session. One that never got a word is
   * dropped entirely, since an empty turn reads as a glitch.
   */
  const closeOut = useCallback(
    (list: ChatEntry[], note?: string): ChatEntry[] =>
      list
        .filter((entry) => !(entry.streaming && !entry.content))
        .map((entry) =>
          entry.streaming
            ? { ...entry, streaming: false, truncated: note ?? entry.truncated }
            : entry,
        ),
    [],
  );

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
      setLastQuestion(text);

      // Abandon a still-running question rather than interleaving two answers.
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;

      const asked: ChatEntry = { id: nextId.current++, role: "user", content: text };
      // A question asked over a running answer supersedes it.
      const history = [...closeOut(entriesRef.current), asked];
      // The answer's place in the conversation is claimed now and filled in
      // as it arrives, so nothing below it jumps as the text grows.
      const answerId = nextId.current++;
      commit([...history, { id: answerId, role: "assistant", content: "", streaming: true }]);

      const turns: ChatTurn[] = history
        .filter((entry) => !entry.failed && entry.content.trim())
        .slice(-HISTORY_LIMIT)
        .map((entry) => ({ role: entry.role, content: entry.content }));

      setPending(true);
      setStreaming(false);
      const { page: askedOn, readId: openRead, rangeDays: days } = scope.current;
      const body = {
        messages: turns,
        page: askedOn,
        read_id: askedOn === "read" ? openRead : null,
        range_days: days,
      };

      // Tokens arrive far faster than the screen refreshes, so they are
      // collected and written once per frame. Rendering each one separately
      // is what makes a streamed answer stutter.
      let buffered = "";
      let frame = 0;
      const flush = () => {
        frame = 0;
        if (!buffered || controller.signal.aborted) return;
        const chunk = buffered;
        buffered = "";
        patch(answerId, (entry) => ({ ...entry, content: entry.content + chunk }));
      };
      const schedule = () => {
        if (frame || controller.signal.aborted) return;
        frame = requestAnimationFrame(flush);
      };
      const settle = () => {
        if (frame) cancelAnimationFrame(frame);
        frame = 0;
        flush();
      };

      const streamed = api.chatStream(
        body,
        {
          onMeta: (meta) => {
            if (controller.signal.aborted) return;
            patch(answerId, (entry) => ({
              ...entry,
              groundedOn: meta.grounded_on,
              unready: !meta.ready,
            }));
          },
          onStart: (model) => {
            if (controller.signal.aborted) return;
            setPending(false);
            setStreaming(true);
            patch(answerId, (entry) => ({ ...entry, model }));
          },
          onDelta: (chunk) => {
            buffered += chunk;
            schedule();
          },
          onDone: (done) => {
            settle();
            if (controller.signal.aborted) return;
            patch(answerId, (entry) => ({
              ...entry,
              streaming: false,
              model: done.model || entry.model,
              truncated: done.error || undefined,
            }));
          },
        },
        controller.signal,
      );

      streamed
        .catch((err: unknown) => {
          settle();
          if (controller.signal.aborted) throw err;
          // An older server that has the buffered route but not the streaming
          // one: ask again the slow way rather than showing a failure.
          if (err instanceof StreamUnsupported) {
            return api.chatSend(body, controller.signal).then((res) => {
              if (controller.signal.aborted) return;
              patch(answerId, (entry) => ({
                ...entry,
                content: res.reply,
                groundedOn: res.grounded_on,
                model: res.model,
                unready: !res.ready,
                streaming: false,
              }));
            });
          }
          throw err;
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
          patch(answerId, (entry) =>
            entry.content
              ? // Something useful did arrive; keep it and say why it stopped.
                { ...entry, streaming: false, truncated: message }
              : { ...entry, content: message, failed: true, streaming: false },
          );
        })
        .finally(() => {
          if (controller.signal.aborted) return;
          setPending(false);
          setStreaming(false);
        });
    },
    [closeOut, commit, patch],
  );

  const stop = useCallback(() => {
    inFlight.current?.abort();
    inFlight.current = null;
    setPending(false);
    setStreaming(false);
    commit(closeOut(entriesRef.current, "You stopped this answer."));
  }, [closeOut, commit]);

  const retry = useCallback(() => {
    const question = lastQuestion;
    if (!question) return;
    inFlight.current?.abort();
    inFlight.current = null;
    // Drop the failed exchange so the retry does not send its own error
    // message back as conversation history.
    const trimmed = [...entriesRef.current];
    while (trimmed.length && trimmed[trimmed.length - 1].role === "assistant") trimmed.pop();
    if (trimmed.length && trimmed[trimmed.length - 1].role === "user") trimmed.pop();
    commit(trimmed);
    ask(question);
  }, [ask, commit, lastQuestion]);

  const openDock = useCallback((seed?: string) => {
    setOpen(true);
    if (seed) setDraft(seed);
  }, []);

  const closeDock = useCallback(() => {
    setOpen(false);
  }, []);

  const clear = useCallback(() => {
    inFlight.current?.abort();
    inFlight.current = null;
    commit([]);
    setError(null);
    setPending(false);
    setStreaming(false);
    setLastQuestion(null);
  }, [commit]);

  const value = useMemo<ChatContextValue>(
    () => ({
      enabled,
      open,
      page,
      entries,
      pending,
      streaming,
      error,
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
    }),
    [
      enabled,
      open,
      page,
      entries,
      pending,
      streaming,
      error,
      suggestions,
      draft,
      lastQuestion,
      openDock,
      closeDock,
      ask,
      stop,
      retry,
      clear,
    ],
  );

  return <ChatCtx.Provider value={value}>{children}</ChatCtx.Provider>;
}
