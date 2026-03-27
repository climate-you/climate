"use client";

import React, { useEffect, useRef, useState } from "react";
import styles from "./ChatDrawer.module.css";
import {
  CHAT_EXAMPLE_QUESTIONS_GENERIC,
  CHAT_MODEL_OVERRIDE_KEY,
  CHAT_OPT_OUT_KEY,
  CHAT_PRIVACY_NOTICE,
} from "@/lib/explorer/constants";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type MapContext = { lat: number; lon: number; label: string } | null;
type ModelOverride = "groq_8b" | "local" | null;

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  messageId?: string;
  notice?: string;       // degraded-model disclaimer
  feedback?: "good" | "bad" | null;
  error?: boolean;
  loading?: boolean;
};

type ChatDrawerProps = {
  apiBase: string;
  mapContext: MapContext;
  devMode?: boolean;     // shows the model toggle when true
};

// ---------------------------------------------------------------------------
// SSE helpers
// ---------------------------------------------------------------------------

async function streamChatRequest(
  apiBase: string,
  payload: object,
  onEvent: (event: Record<string, unknown>) => void,
): Promise<void> {
  const res = await fetch(`${apiBase}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      for (const line of part.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        try {
          onEvent(JSON.parse(line.slice(6)) as Record<string, unknown>);
        } catch {
          // ignore malformed SSE lines
        }
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ChatDrawer({
  apiBase,
  mapContext,
  devMode = false,
}: ChatDrawerProps) {
  const [open, setOpen] = useState(false);
  const [conversationId] = useState(() => crypto.randomUUID());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [optOut, setOptOut] = useState(false);
  const [modelOverride, setModelOverride] = useState<ModelOverride>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Read persisted preferences from localStorage (client-side only)
  useEffect(() => {
    setOptOut(localStorage.getItem(CHAT_OPT_OUT_KEY) === "1");
    const stored = localStorage.getItem(CHAT_MODEL_OVERRIDE_KEY);
    if (stored === "groq_8b" || stored === "local") {
      setModelOverride(stored);
    }
  }, []);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when drawer opens
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // Keyboard: close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open]);

  function persistOptOut(value: boolean) {
    setOptOut(value);
    if (value) {
      localStorage.setItem(CHAT_OPT_OUT_KEY, "1");
    } else {
      localStorage.removeItem(CHAT_OPT_OUT_KEY);
    }
  }

  function persistModelOverride(value: ModelOverride) {
    setModelOverride(value);
    if (value) {
      localStorage.setItem(CHAT_MODEL_OVERRIDE_KEY, value);
    } else {
      localStorage.removeItem(CHAT_MODEL_OVERRIDE_KEY);
    }
  }

  async function sendMessage(question: string) {
    if (!question.trim() || loading) return;
    setInput("");
    setLoading(true);

    const messageId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { role: "user", text: question },
      { role: "assistant", text: "", messageId, loading: true },
    ]);


    let pendingNotice: string | undefined;
    let answered = false;

    try {
      await streamChatRequest(
        apiBase,
        {
          question,
          map_context: mapContext,
          opt_out: optOut,
          session_id: conversationId,
          message_id: messageId,
          model_override: modelOverride ?? undefined,
        },
        (event) => {
          const type = event.type as string;
          if (type === "notice") {
            pendingNotice = event.text as string;
          } else if (type === "answer") {
            answered = true;
            setMessages((prev) =>
              prev.map((m) =>
                m.messageId === messageId
                  ? {
                      ...m,
                      text: event.text as string,
                      notice: pendingNotice,
                      loading: false,
                    }
                  : m,
              ),
            );
          } else if (type === "error") {
            setMessages((prev) =>
              prev.map((m) =>
                m.messageId === messageId
                  ? {
                      ...m,
                      text: event.message as string,
                      loading: false,
                      error: true,
                    }
                  : m,
              ),
            );
          }
        },
      );

      if (!answered) {
        // Stream ended without an answer event
        setMessages((prev) =>
          prev.map((m) =>
            m.messageId === messageId
              ? { ...m, text: "No response received.", loading: false, error: true }
              : m,
          ),
        );
      }
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.messageId === messageId
            ? {
                ...m,
                text: "Failed to connect to the assistant. Please try again.",
                loading: false,
                error: true,
              }
            : m,
        ),
      );
    } finally {
      setLoading(false);
    }
  }

  async function submitFeedback(
    messageId: string,
    feedback: "good" | "bad" | null,
  ) {
    // Toggle: clicking the active state clears feedback
    const current = messages.find((m) => m.messageId === messageId)?.feedback;
    const next = current === feedback ? null : feedback;
    setMessages((prev) =>
      prev.map((m) => (m.messageId === messageId ? { ...m, feedback: next } : m)),
    );
    try {
      await fetch(`${apiBase}/api/chat/${messageId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback: next }),
      });
    } catch {
      // Feedback is best-effort; don't surface errors
    }
  }

  function handleInputKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage(input);
    }
  }

  const exampleQuestions =
    mapContext?.label
      ? [
          `What was the hottest year on record in ${mapContext.label}?`,
          `How have temperatures changed in ${mapContext.label} since 2000?`,
          `What was the annual mean temperature in ${mapContext.label} in 2020?`,
        ]
      : CHAT_EXAMPLE_QUESTIONS_GENERIC;

  const isEmpty = messages.length === 0;

  return (
    <>
      {/* Floating chat button */}
      <button
        type="button"
        className={`${styles.chatButton} ${open ? styles.chatButtonOpen : ""}`}
        aria-label={open ? "Close chat" : "Open climate data assistant"}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? (
          <svg viewBox="0 0 24 24" aria-hidden="true" className={styles.chatButtonIcon}>
            <path d="M6 6L18 18M18 6L6 18" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" aria-hidden="true" className={styles.chatButtonIcon}>
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        )}
      </button>

      {/* Drawer */}
      {open && (
        <aside
          className={styles.drawer}
          role="dialog"
          aria-label="Climate data assistant"
          aria-modal="false"
        >
          {/* Header */}
          <div className={styles.drawerHeader}>
            <div className={styles.drawerTitle}>
              <svg viewBox="0 0 24 24" aria-hidden="true" className={styles.drawerTitleIcon}>
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
              Climate Assistant
            </div>

            {/* Dev model toggle */}
            {devMode && (
              <div className={styles.modelToggle} role="group" aria-label="Model">
                <button
                  type="button"
                  className={`${styles.modelToggleBtn} ${!modelOverride || modelOverride === "groq_8b" ? styles.modelToggleBtnActive : ""}`}
                  onClick={() => persistModelOverride("groq_8b")}
                >
                  8b
                </button>
                <button
                  type="button"
                  className={`${styles.modelToggleBtn} ${modelOverride === "local" ? styles.modelToggleBtnActive : ""}`}
                  onClick={() => persistModelOverride("local")}
                >
                  local
                </button>
              </div>
            )}

            <button
              type="button"
              className={styles.drawerClose}
              aria-label="Close chat"
              onClick={() => setOpen(false)}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M6 6L18 18M18 6L6 18" />
              </svg>
            </button>
          </div>

          {/* Messages */}
          <div className={styles.messages}>
            {isEmpty && (
              <div className={styles.emptyState}>
                <p className={styles.emptyStateHint}>
                  Ask a question about climate data, or try one of these:
                </p>
                <div className={styles.chips}>
                  {exampleQuestions.map((q) => (
                    <button
                      key={q}
                      type="button"
                      className={styles.chip}
                      onClick={() => void sendMessage(q)}
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              <div
                key={i}
                className={`${styles.message} ${msg.role === "user" ? styles.messageUser : styles.messageAssistant}`}
              >
                {msg.notice && (
                  <div className={styles.noticeBar}>{msg.notice}</div>
                )}
                <div
                  className={`${styles.messageBubble} ${msg.error ? styles.messageBubbleError : ""}`}
                >
                  {msg.loading ? (
                    <span className={styles.loadingDots}>
                      <span />
                      <span />
                      <span />
                    </span>
                  ) : (
                    msg.text
                  )}
                </div>

                {/* Feedback buttons for assistant messages */}
                {msg.role === "assistant" && msg.messageId && !msg.loading && !msg.error && (
                  <div className={styles.feedback}>
                    <button
                      type="button"
                      className={`${styles.feedbackBtn} ${msg.feedback === "good" ? styles.feedbackBtnActive : ""}`}
                      aria-label="Good answer"
                      aria-pressed={msg.feedback === "good"}
                      onClick={() => void submitFeedback(msg.messageId!, "good")}
                    >
                      👍
                    </button>
                    <button
                      type="button"
                      className={`${styles.feedbackBtn} ${msg.feedback === "bad" ? styles.feedbackBtnActive : ""}`}
                      aria-label="Bad answer"
                      aria-pressed={msg.feedback === "bad"}
                      onClick={() => void submitFeedback(msg.messageId!, "bad")}
                    >
                      👎
                    </button>
                  </div>
                )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Privacy notice */}
          <div className={styles.privacyBar}>
            <span>{CHAT_PRIVACY_NOTICE}</span>
            <button
              type="button"
              className={`${styles.optOutBtn} ${optOut ? styles.optOutBtnActive : ""}`}
              onClick={() => persistOptOut(!optOut)}
            >
              {optOut ? "Opted out" : "Opt out"}
            </button>
          </div>

          {/* Input */}
          <div className={styles.inputRow}>
            <textarea
              ref={inputRef}
              className={styles.input}
              rows={1}
              placeholder="Ask about climate data…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleInputKeyDown}
              disabled={loading}
              aria-label="Chat input"
            />
            <button
              type="button"
              className={styles.sendBtn}
              aria-label="Send"
              disabled={!input.trim() || loading}
              onClick={() => void sendMessage(input)}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z" />
              </svg>
            </button>
          </div>
        </aside>
      )}
    </>
  );
}
