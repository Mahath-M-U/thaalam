import { useState } from "react";
import { api } from "../api";
import type { DailyBriefResponse } from "../types";
import { ChartCard } from "./ChartCard";

interface Props {
  brief: DailyBriefResponse;
}

const QUESTIONS: { key: string; label: string }[] = [
  { key: "recovery_drivers", label: "Why is my recovery at this level today?" },
  { key: "training_load", label: "Am I training too much?" },
  { key: "sleep_debt", label: "How is my sleep debt?" },
  { key: "push_or_rest", label: "Should I push hard today or take it easy?" },
];

interface ExplainerState {
  loading: boolean;
  answer: string | null;
  error: string | null;
}

export function DailyBriefCard({ brief }: Props) {
  const [open, setOpen] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, ExplainerState>>({});

  const askQuestion = async (key: string) => {
    if (open === key) {
      setOpen(null);
      return;
    }
    setOpen(key);
    if (answers[key]?.answer) return;

    setAnswers((prev) => ({ ...prev, [key]: { loading: true, answer: null, error: null } }));
    try {
      const res = await api.briefExplain(key);
      setAnswers((prev) => ({ ...prev, [key]: { loading: false, answer: res.answer, error: null } }));
    } catch (err) {
      setAnswers((prev) => ({
        ...prev,
        [key]: {
          loading: false,
          answer: null,
          error: err instanceof Error ? err.message : String(err),
        },
      }));
    }
  };

  return (
    <ChartCard
      title="Daily brief"
      description="A short, rule-based read of today's numbers — deterministic, no AI involved."
      wide
    >
      <p className="brief-text">
        {brief.ready ? brief.brief : (brief.message ?? "Not enough data yet.")}
      </p>

      {brief.ready && (
        <div className="brief-questions">
          {QUESTIONS.map((q) => (
            <div key={q.key} className="brief-question">
              <button
                type="button"
                className={`btn ghost brief-question-btn${open === q.key ? " active" : ""}`}
                onClick={() => void askQuestion(q.key)}
              >
                {q.label}
              </button>
              {open === q.key && (
                <div className="brief-answer">
                  {answers[q.key]?.loading && <span className="muted">Loading…</span>}
                  {answers[q.key]?.error && (
                    <span className="brief-answer-error">{answers[q.key]?.error}</span>
                  )}
                  {answers[q.key]?.answer && <p>{answers[q.key]?.answer}</p>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </ChartCard>
  );
}
