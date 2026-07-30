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
  PENDING: "В очереди локального worker",
  LEASED: "Анализ и построение",
  WAITING_FOR_USER_ANSWERS: "Нужно уточнение",
  READY: "Модель готова",
  FAILED: "Построение остановлено",
};

const artifactOrder = ["M3D", "STEP", "STL", "VALIDATION_REPORT"];

export default function Home() {
  const [token, setToken] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);
  const [orderId, setOrderId] = useState<string | null>(null);
  const [order, setOrder] = useState<OrderState | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setToken(sessionStorage.getItem("cad-ai-token") ?? "");
    setComment(localStorage.getItem("cad-ai-drawing-note") ?? "");
    setOrderId(new URLSearchParams(window.location.search).get("order"));
  }, []);

  useEffect(() => {
    if (!file) {
      setSourceUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setSourceUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    localStorage.setItem("cad-ai-drawing-note", comment);
  }, [comment]);

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
  const artifacts = useMemo(
    () => artifactOrder
      .map((type) => order?.artifacts.find((artifact) => artifact.type.toUpperCase() === type))
      .filter((artifact): artifact is Artifact => Boolean(artifact)),
    [order],
  );
  const activeStatus = order?.status ?? (file ? "DRAFT" : "EMPTY");

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
      link.download = `cad-result.${extensionFor(artifact.type)}`;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (reason) {
      setError(message(reason));
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">◇</span>
          <span>cad.ai<span>/</span>studio</span>
        </div>

        <form className="side-scroll" onSubmit={submitDrawing}>
          <section className="side-section connection">
            <div className="section-label">Подключение</div>
            <label className="compact-label" htmlFor="token">Локальный API-токен</label>
            <input
              id="token"
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="Токен из .env"
              autoComplete="off"
            />
            <p className="connection-note"><i /> Auth остаётся только в этом браузере</p>
          </section>

          <section className="side-section">
            <div className="section-heading">
              <span className="section-label">Исходный чертёж</span>
              <span className="file-kind">PNG / JPG</span>
            </div>
            <label className={`upload-drop ${file ? "has-file" : ""}`}>
              <input
                type="file"
                accept="image/png,image/jpeg"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              <span className="upload-icon">↑</span>
              <strong>{file ? file.name : "Перетащите или выберите файл"}</strong>
              <small>{file ? formatBytes(file.size) : "PNG или JPEG, до 25 МБ"}</small>
            </label>
          </section>

          <section className="side-section">
            <div className="section-label">Режим моделирования</div>
            <div className="mode-card">
              <span className="mode-orb" />
              <span><b>Деталь · MVP</b><small>Призма и сквозные отверстия</small></span>
              <span className="mode-check">✓</span>
            </div>
            <div className="capability-list" aria-label="Поддерживаемые возможности">
              <span>Призма</span><span>Отверстия</span><span>STEP / STL</span>
            </div>
          </section>

          <section className="side-section notes-section">
            <div className="section-heading">
              <span className="section-label">Комментарий к чертежу</span>
              <span className="local-tag">локально</span>
            </div>
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder="Например: отверстие должно быть сквозным…"
              maxLength={1000}
            />
            <p className="field-hint">Черновик остаётся в браузере: API ещё не принимает комментарии.</p>
          </section>

          <button className="primary-action" type="submit" disabled={busy}>
            <span>{busy ? "Создаём задание…" : "Построить модель"}</span>
            <b>→</b>
          </button>
          {error && <p className="error side-error">{error}</p>}
        </form>

        <div className="sidebar-footer"><span>LOCAL-FIRST</span><span>v0.4</span></div>
      </aside>

      <section className="workbench">
        <header className="topbar">
          <div>
            <p className="crumb">Рабочее пространство <span>/</span> Новая деталь</p>
            <h1>{order ? "Обработка чертежа" : "Создайте проверенную 3D-модель"}</h1>
          </div>
          <div className={`status-pill status-${activeStatus.toLowerCase()}`}>
            <i /> {statusCopy[activeStatus] ?? (activeStatus === "DRAFT" ? "Черновик" : "Ожидание файла")}
          </div>
        </header>

        <div className="canvas-frame">
          <div className="canvas-toolbar">
            <span>{stl ? "3D preview" : sourceUrl ? "Drawing preview" : "Preview"}</span>
            <span className="toolbar-divider" />
            <span>{stl ? "STL · validated" : "MM · технический чертёж"}</span>
          </div>

          {stl ? (
            <StlPreview url={`${API_URL}${stl.download_url}`} token={token} />
          ) : sourceUrl ? (
            <div className="drawing-preview"><img src={sourceUrl} alt="Загруженный чертёж" /></div>
          ) : (
            <div className="empty-canvas">
              <div className="empty-grid-mark"><span /><span /><span /></div>
              <strong>Здесь будет модель</strong>
              <p>Загрузите чертёж слева — покажем его и итоговую 3D-геометрию.</p>
            </div>
          )}

          {!stl && <div className="canvas-hud"><span>XY</span><span>Z ↑</span></div>}
        </div>

        {order?.waiting_reason && order.questions.length === 0 && (
          <p className="waiting-reason">{order.waiting_reason}</p>
        )}

        {order?.questions.length ? (
          <form className="clarification-card" onSubmit={submitAnswers}>
            <div className="assistant-avatar">AI</div>
            <div className="clarification-content">
              <span className="section-label">Нужно уточнение</span>
              <h2>Перед построением подтвердите размеры</h2>
              <p>Ответы попадут в следующий typed CAD-IR; подтверждённые размеры не меняются автоматически.</p>
              <div className="question-grid">
                {order.questions.map((question) => (
                  <label key={question.id} className="question-field">
                    <span>{question.text}</span>
                    <div><input
                      type="number"
                      min="0.001"
                      step="any"
                      value={answers[question.id] ?? ""}
                      onChange={(event) => setAnswers((current) => ({ ...current, [question.id]: event.target.value }))}
                      required
                    /><b>мм</b></div>
                  </label>
                ))}
              </div>
              <button className="answer-button" disabled={busy}>Продолжить анализ <span>→</span></button>
            </div>
          </form>
        ) : null}
      </section>

      <aside className="result-rail">
        <div className="result-heading">
          <div><span className="section-label">Результат</span><h2>Выходные данные</h2></div>
          <span className="result-count">{artifacts.length}/4</span>
        </div>

        <div className="progress-card">
          <div className="progress-ring"><span>{order?.status === "READY" ? "100" : order ? "…" : "0"}</span></div>
          <div><b>{statusCopy[activeStatus] ?? "Новая задача"}</b><small>{order ? `Job ${order.job_id.slice(0, 8)}` : "Загрузите чертёж для начала"}</small></div>
        </div>

        <ol className="timeline">
          <li className={order ? "done" : ""}><i />Чертёж загружен</li>
          <li className={order?.status === "LEASED" || order?.status === "READY" ? "done" : ""}><i />Анализ и CAD-IR</li>
          <li className={order?.status === "READY" ? "done" : ""}><i />Валидация геометрии</li>
        </ol>

        <section className="downloads">
          <div className="section-heading"><span className="section-label">Артефакты</span><span>{artifacts.length ? "Готовы" : "Ожидаются"}</span></div>
          {artifactOrder.map((type) => {
            const artifact = artifacts.find((item) => item.type.toUpperCase() === type);
            return artifact ? (
              <button className="download-card" type="button" key={type} onClick={() => void download(artifact)}>
                <span className="artifact-icon">{type === "VALIDATION_REPORT" ? "✓" : "↓"}</span>
                <span><b>{artifactLabel(type)}</b><small>{formatBytes(artifact.size_bytes)} · SHA-256</small></span>
                <span className="download-arrow">→</span>
              </button>
            ) : (
              <div className="download-card disabled" key={type}>
                <span className="artifact-icon">{type === "VALIDATION_REPORT" ? "✓" : "↓"}</span>
                <span><b>{artifactLabel(type)}</b><small>Появится после построения</small></span>
              </div>
            );
          })}
        </section>

        <div className="security-note"><span>◇</span><p><b>Trusted local build</b>Codex auth и лицензия КОМПАС не покидают ваш ПК.</p></div>
      </aside>
    </main>
  );
}

function artifactLabel(type: string) {
  return type === "VALIDATION_REPORT" ? "Отчёт проверки" : type;
}

function extensionFor(type: string) {
  return ({ M3D: "m3d", STEP: "step", STL: "stl", VALIDATION_REPORT: "json" } as Record<string, string>)[type] ?? "bin";
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} Б`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} КБ`;
  return `${(value / (1024 * 1024)).toFixed(1)} МБ`;
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
