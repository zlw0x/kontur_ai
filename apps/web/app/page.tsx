"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import StlPreview from "./stl-preview";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Question = { id: string; parameter_id: string; text: string };
type Artifact = {
  type: string;
  size_bytes: number;
  sha256: string;
  download_url: string;
};
type OrderState = {
  order_id: string;
  job_id: string;
  status: string;
  waiting_reason: string | null;
  round: number;
  questions: Question[];
  artifacts: Artifact[];
};

const statusCopy: Record<string, string> = {
  PENDING: "Ожидает локальный worker",
  LEASED: "Анализируем и строим модель",
  WAITING_FOR_USER_ANSWERS: "Нужно уточнение",
  READY: "Модель готова",
};

export default function Home() {
  const [token, setToken] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [orderId, setOrderId] = useState<string | null>(null);
  const [order, setOrder] = useState<OrderState | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setToken(sessionStorage.getItem("cad-ai-token") ?? "");
    setOrderId(new URLSearchParams(window.location.search).get("order"));
  }, []);

  useEffect(() => {
    if (!orderId || !token) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(`${API_URL}/api/v1/drawing-jobs/${orderId}`, {
          headers: { "x-manual-api-token": token },
          cache: "no-store",
        });
        if (!response.ok) throw new Error(await safeError(response));
        const value = (await response.json()) as OrderState;
        if (!cancelled) {
          setOrder(value);
          setError("");
        }
      } catch (reason) {
        if (!cancelled) setError(message(reason));
      }
    };
    void poll();
    const timer = window.setInterval(poll, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [orderId, token]);

  const stl = useMemo(
    () => order?.artifacts.find((artifact) => artifact.type.toUpperCase() === "STL"),
    [order],
  );

  async function submitDrawing(event: FormEvent) {
    event.preventDefault();
    if (!file || !token) {
      setError("Выберите PNG/JPEG и укажите локальный API-токен.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      sessionStorage.setItem("cad-ai-token", token);
      const response = await fetch(`${API_URL}/api/v1/drawing-jobs`, {
        method: "POST",
        headers: {
          "content-type": file.type,
          "x-manual-api-token": token,
        },
        body: file,
      });
      if (!response.ok) throw new Error(await safeError(response));
      const created = (await response.json()) as { order_id: string };
      setOrder(null);
      setAnswers({});
      setOrderId(created.order_id);
      window.history.replaceState(null, "", `?order=${created.order_id}`);
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  async function submitAnswers(event: FormEvent) {
    event.preventDefault();
    if (!order) return;
    setBusy(true);
    setError("");
    try {
      const payload = order.questions.map((question) => ({
        question_id: question.id,
        value: Number(answers[question.id]),
        unit: "mm",
      }));
      if (payload.some((answer) => !Number.isFinite(answer.value))) {
        throw new Error("Заполните все размеры числовыми значениями.");
      }
      const response = await fetch(`${API_URL}/api/v1/drawing-jobs/${order.order_id}/answers`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-manual-api-token": token,
        },
        body: JSON.stringify({ answers: payload }),
      });
      if (!response.ok) throw new Error(await safeError(response));
      setOrder(null);
      setAnswers({});
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  async function download(artifact: Artifact) {
    setError("");
    try {
      const response = await fetch(`${API_URL}${artifact.download_url}`, {
        headers: { "x-manual-api-token": token },
      });
      if (!response.ok) throw new Error(await safeError(response));
      const blob = await response.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `model.${artifact.type.toLowerCase()}`;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (reason) {
      setError(message(reason));
    }
  }

  return (
    <main>
      <header className="hero">
        <p className="eyebrow">CAD AI SERVICE · LOCAL-FIRST</p>
        <h1>Из чертежа — в проверенную 3D‑модель.</h1>
        <p className="lead">
          Анализ выполняется локально через вашу авторизацию Codex. KOMPAS‑3D строит модель,
          а независимый валидатор проверяет размеры, тело и отверстия.
        </p>
      </header>

      <section className="workspace">
        <form className="panel upload-panel" onSubmit={submitDrawing}>
          <div className="step">01 · Входные данные</div>
          <label>
            Локальный API-токен
            <input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="Введите токен из .env"
              autoComplete="off"
            />
          </label>
          <label className="drop">
            <span>{file ? file.name : "Выберите чертёж PNG или JPEG"}</span>
            <small>До 25 МБ · простой призматический объект MVP</small>
            <input
              type="file"
              accept="image/png,image/jpeg"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <button type="submit" disabled={busy}>
            {busy ? "Отправляем…" : "Запустить построение"}
          </button>
          {error && <p className="error">{error}</p>}
        </form>

        <section className="panel result-panel">
          <div className="step">02 · Результат</div>
          {!order && (
            <div className="empty">
              <div className="cube-mark" aria-hidden="true">◇</div>
              <p>{orderId ? "Получаем состояние задания…" : "Здесь появятся статус и 3D‑превью."}</p>
            </div>
          )}
          {order && (
            <>
              <div className="status-row">
                <span className={`status status-${order.status.toLowerCase()}`}>
                  {statusCopy[order.status] ?? order.status}
                </span>
                <code>{order.job_id.slice(0, 8)}</code>
              </div>

              {order.waiting_reason && order.questions.length === 0 && (
                /* Why the order has not moved. Without it a queued job and a
                   job no worker can serve look identical from here. */
                <p className="waiting-reason">{order.waiting_reason}</p>
              )}

              {order.questions.length > 0 && (
                <form className="questions" onSubmit={submitAnswers}>
                  <h2>Уточните размеры</h2>
                  {order.questions.map((question) => (
                    <label key={question.id}>
                      {question.text}
                      <span className="number-field">
                        <input
                          type="number"
                          min="0.001"
                          step="any"
                          value={answers[question.id] ?? ""}
                          onChange={(event) =>
                            setAnswers((current) => ({ ...current, [question.id]: event.target.value }))
                          }
                          required
                        />
                        <b>мм</b>
                      </span>
                    </label>
                  ))}
                  <button disabled={busy}>Продолжить анализ</button>
                </form>
              )}

              {stl && (
                <StlPreview
                  url={`${API_URL}${stl.download_url}`}
                  token={token}
                />
              )}

              {order.artifacts.length > 0 && (
                <div className="artifacts">
                  {order.artifacts
                    .filter((artifact) => ["M3D", "STEP", "STL", "VALIDATION_REPORT"].includes(artifact.type))
                    .map((artifact) => (
                      <button
                        className="artifact"
                        type="button"
                        key={artifact.type}
                        onClick={() => void download(artifact)}
                      >
                        <span>{artifact.type.replace("_", " ")}</span>
                        <small>{formatBytes(artifact.size_bytes)}</small>
                      </button>
                    ))}
                </div>
              )}
            </>
          )}
        </section>
      </section>

      <footer>
        <span>Codex auth и лицензия KOMPAS никогда не передаются на VPS.</span>
        <span>CAD‑IR 0.1.0 · typed jobs · SHA‑256</span>
      </footer>
    </main>
  );
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} Б`;
  return `${(value / 1024).toFixed(1)} КБ`;
}

function message(reason: unknown) {
  return reason instanceof Error ? reason.message : "Неизвестная ошибка.";
}

async function safeError(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    return typeof payload.detail === "string" ? payload.detail : `Ошибка ${response.status}`;
  } catch {
    return `Ошибка ${response.status}`;
  }
}
