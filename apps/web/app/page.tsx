"use client";

import { DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import StlPreview from "./stl-preview";
import LandingPage from "./landing-page";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Question = {
  id: string;
  parameter_id: string;
  text: string;
  // How the question is answered. Absent on a question written before the
  // reading stage said so, and those were all numbers.
  answer_kind?: "number" | "choice";
  choices?: string[];
};
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
  // Present only when the order failed. Both are written by the worker and are
  // safe to show: a typed code and text already stripped of paths and hosts.
  failure_code?: string | null;
  failure_message?: string | null;
  // Present only on a pause: when the service expects to be able to try again.
  retry_after?: string | null;
  round: number;
  questions: Question[];
  artifacts: Artifact[];
};
type Dimensions = { length: number; width: number; height: number };
type ViewMode = "model" | "drawing";
type Material = "aluminum" | "steel" | "polymer";
type IconName =
  | "arrow"
  | "box"
  | "check"
  | "chevron"
  | "cube"
  | "download"
  | "expand"
  | "file"
  | "image"
  | "info"
  | "layers"
  | "plus"
  | "refresh"
  | "settings"
  | "sparkles"
  | "trash"
  | "upload";

// The order results are shown in: two files and the report they were checked
// with, which is ADR-023's whole answer to what a customer gets.
const artifactOrder = ["STEP", "STL", "VALIDATION_REPORT"];
// One vocabulary. The API used to answer with `OrderStatus` on two branches and
// `JobStatus` on the third — READY and WAITING_FOR_USER_ANSWERS from one set,
// PENDING and LEASED from the other — so this map had to cover both and which
// half a customer saw depended on which branch fired. Since the orders table it
// is `OrderStatus` throughout.
const statusCopy: Record<string, string> = {
  WAITING_FOR_LOCAL_WORKER: "Ожидает запуска",
  DRAWING_ANALYSIS: "Читаем чертёж",
  CAD_BUILDING: "Создаём модель",
  CAD_VALIDATION: "Проверяем геометрию",
  WAITING_FOR_USER_ANSWERS: "Уточните размеры",
  READY: "Модель готова",
  FAILED: "Нужна проверка",
  PAUSED: "Пауза, вернёмся",
  MANUAL_REVIEW: "Смотрит инженер",
  CANCELLED: "Заказ отменён",
  EXPIRED: "Срок заказа истёк",
};

// The states where a worker is holding the order and the page should look busy.
// A set rather than a comparison with "LEASED": the stage is now named, and three
// names mean three places to forget one.
const working = new Set(["DRAWING_ANALYSIS", "CAD_BUILDING", "CAD_VALIDATION"]);
const materialOptions: { value: Material; label: string; color: string }[] = [
  { value: "aluminum", label: "Алюминий", color: "#c8d2d5" },
  { value: "steel", label: "Сталь", color: "#aeb7c1" },
  { value: "polymer", label: "Полимер", color: "#b8f35a" },
];

export default function Home() {
  const [showLanding, setShowLanding] = useState(true);
  const fileInput = useRef<HTMLInputElement>(null);
  const [token, setToken] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);
  const [orderId, setOrderId] = useState<string | null>(null);
  const [order, setOrder] = useState<OrderState | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [comment, setComment] = useState("");
  const [material, setMaterial] = useState<Material>("aluminum");
  const [precision, setPrecision] = useState<"standard" | "high">("high");
  const [viewMode, setViewMode] = useState<ViewMode>("model");
  // What a new order asks for: everything a build delivers.
  const [outputs, setOutputs] = useState<Record<string, boolean>>({
    STEP: true,
    STL: true,
    VALIDATION_REPORT: true,
  });
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  /**
   * What was measured on the model that was actually built.
   *
   * Read out of the validation report the worker wrote from the exported file.
   * The page has no other way to know a size, so until this arrives it states
   * none: the summary used to fall back to 80 x 40 x 12, which is a number out
   * of the layout, and it was shown next to a real 60 x 30 x 8 plate.
   */
  const [measured, setMeasured] = useState<Dimensions | null>(null);
  /** The sizes the visitor confirmed, shown until a model has been measured. */
  const [confirmed, setConfirmed] = useState<Dimensions | null>(null);

  useEffect(() => {
    setShowLanding(!window.location.pathname.startsWith("/studio"));
    const storedToken = sessionStorage.getItem("cad-ai-token") ?? "";
    setToken(storedToken);
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
          if (value.status === "READY") setViewMode("model");
          setError("");
          reschedule(value.status);
        }
      } catch (reason) {
        if (!cancelled) setError(message(reason));
      }
    };

    /*
      How soon to ask again, from what the last answer was.

      A fixed three-second interval never stopped. A finished order was polled for
      as long as the tab stayed open, and a *paused* one — an exhausted model quota
      returns on a date — would be polled roughly a hundred thousand times over four
      days to be told the same thing.

      READY and FAILED are ends: nothing else will happen and the timer stops. PAUSED
      is not an end, so it is asked about once a minute rather than never: the pause
      lifts on the server, and a page that had stopped looking would show a stale
      pause until somebody reloaded.
    */
    let timer: number | undefined;
    const reschedule = (status: string) => {
      window.clearTimeout(timer);
      if (cancelled || status === "READY" || status === "FAILED") return;
      timer = window.setTimeout(poll, status === "PAUSED" ? 60_000 : 3_000);
    };

    void poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [orderId, token]);

  const stl = useMemo(
    () => order?.artifacts.find((artifact) => artifact.type.toUpperCase() === "STL"),
    [order],
  );
  const report = useMemo(
    () => order?.artifacts.find((artifact) => artifact.type.toUpperCase() === "VALIDATION_REPORT"),
    [order],
  );

  useEffect(() => {
    if (!token || !report || order?.status !== "READY") return;
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`${API_URL}${report.download_url}`, {
          headers: { "x-manual-api-token": token },
          cache: "no-store",
        });
        if (!response.ok) return;
        const box = readBoundingBox(await response.json());
        if (!cancelled && box) setMeasured(box);
      } catch {
        // The model is delivered either way. A report the page cannot read means
        // it says nothing about the size, not that it may invent one.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [order?.status, report?.download_url, report?.sha256, token]);
  const artifacts = useMemo(
    () =>
      artifactOrder
        .map((type) => order?.artifacts.find((artifact) => artifact.type.toUpperCase() === type))
        .filter((artifact): artifact is Artifact => Boolean(artifact)),
    [order],
  );
  const activeStatus = order?.status ?? (file ? "DRAFT" : "EMPTY");
  const progress = getProgress(activeStatus);
  const dimensions = measured ?? confirmed;

  if (showLanding) return <LandingPage />;

  function chooseFile(nextFile: File | null) {
    if (!nextFile) return;
    if (!["image/png", "image/jpeg"].includes(nextFile.type)) {
      setError("Загрузите чертёж в формате PNG или JPEG.");
      return;
    }
    if (nextFile.size > 25 * 1024 * 1024) {
      setError("Размер файла не должен превышать 25 МБ.");
      return;
    }
    setFile(nextFile);
    setOrder(null);
    setOrderId(null);
    setAnswers({});
    setMeasured(null);
    setConfirmed(null);
    setError("");
    setViewMode("drawing");
    window.history.replaceState(null, "", window.location.pathname);
  }

  /**
   * Load the sample drawing that ships with the site.
   *
   * Trying the service should not require having a drawing to hand. The sample
   * is the same plate the acceptance run builds, so what a visitor sees here is
   * what the pipeline is actually tested against.
   */
  async function useSampleDrawing() {
    setError("");
    try {
      const response = await fetch("/sample-drawing.png");
      if (!response.ok) throw new Error("Образец чертежа недоступен.");
      const blob = await response.blob();
      chooseFile(new File([blob], "sample-drawing.png", { type: "image/png" }));
    } catch (reason) {
      setError(message(reason));
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files?.[0] ?? null);
  }

  async function submitDrawing(event: FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Сначала загрузите чертёж.");
      fileInput.current?.click();
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (!token) {
        // With no token this is a demonstration: nothing is sent anywhere, no
        // drawing is read, and the "model" below is a fixed box written into this
        // file. It exists to show the shape of the flow.
        //
        // It used to be indistinguishable from the real thing. The questions
        // arrived pre-filled with 80 / 40 / 12 whatever the drawing showed, and
        // the download button handed over a seven-line STEP file and a
        // twelve-triangle STL — a fabricated part, presented as the customer's
        // own. That is the one place in this service where a *result* was
        // invented, and everything else here exists to stop exactly that.
        //
        // So it stays, and says what it is. `isDemo` marks the order; the banner
        // and the disabled downloads are keyed off it.
        const localOrderId = `local-${Date.now()}`;
        setOrderId(localOrderId);
        setOrder({
          order_id: localOrderId,
          job_id: localOrderId,
          status: "DRAWING_ANALYSIS",
          waiting_reason: null,
          round: 0,
          questions: [],
          artifacts: [],
        });
        await delay(780);
        const questions = [
          { id: "local-length", parameter_id: "length", text: "Длина детали" },
          { id: "local-width", parameter_id: "width", text: "Ширина детали" },
          { id: "local-height", parameter_id: "height", text: "Толщина детали" },
        ];
        setAnswers({ "local-length": "80", "local-width": "40", "local-height": "12" });
        setOrder({
          order_id: localOrderId,
          job_id: localOrderId,
          status: "WAITING_FOR_USER_ANSWERS",
          waiting_reason: null,
          round: 0,
          questions,
          artifacts: [],
        });
        return;
      }
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
      setMeasured(null);
      setConfirmed(null);
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
      // A choice is sent as the text that was offered and carries no unit; a
      // dimension carries millimetres. Which one a question wants is the
      // question's to say, and the API checks the answer against it.
      const payload = order.questions.map((question) =>
        question.answer_kind === "choice"
          ? { question_id: question.id, value: answers[question.id] ?? "" }
          : { question_id: question.id, value: Number(answers[question.id]), unit: "mm" },
      );
      if (payload.some((answer) => answer.unit === undefined && !answer.value)) {
        throw new Error("Выберите ответ на каждый вопрос.");
      }
      if (payload.some((answer) =>
        answer.unit !== undefined &&
        (!Number.isFinite(answer.value as number) || (answer.value as number) <= 0))) {
        throw new Error("Проверьте указанные размеры.");
      }
      // What the visitor confirmed, so the summary has something true to show
      // while the model is being built and before its report can be read.
      const of = (parameter: string) =>
        Number(answers[order.questions.find((item) => item.parameter_id === parameter)?.id ?? ""]);
      const box = { length: of("length"), width: of("width"), height: of("height") };
      setConfirmed(
        Object.values(box).every((value) => Number.isFinite(value) && value > 0) ? box : null,
      );
      if (!token) {
        setOrder({ ...order, status: "CAD_BUILDING", questions: [] });
        await delay(1100);
        setOrder({
          ...order,
          status: "READY",
          waiting_reason: null,
          questions: [],
          artifacts: localArtifacts(),
        });
        setViewMode("model");
        return;
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
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  async function download(artifact: Artifact) {
    setError("");
    try {
      if (!token) {
        // The demonstration hands over nothing. What it would hand over is a
        // box written into this file, and a file named `kontur-model.step` is
        // indistinguishable from a real one once it is on somebody's disk — at
        // which point nothing about it says it was never built from a drawing.
        setError(
          "Это демонстрация: модель не строилась, скачивать нечего. " +
          "Для настоящего построения нужен доступ к сервису.",
        );
        return;
      }
      const response = await fetch(`${API_URL}${artifact.download_url}`, {
        headers: { "x-manual-api-token": token },
      });
      if (!response.ok) throw new Error(await safeError(response));
      triggerDownload(await response.blob(), `kontur-model.${extensionFor(artifact.type)}`);
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function downloadSelected() {
    for (const artifact of artifacts.filter((item) => outputs[item.type.toUpperCase()])) {
      await download(artifact);
      await delay(160);
    }
  }

  function resetProject() {
    setFile(null);
    setOrder(null);
    setOrderId(null);
    setAnswers({});
    setError("");
    setViewMode("model");
    if (fileInput.current) fileInput.current.value = "";
    window.history.replaceState(null, "", window.location.pathname);
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Logo />
          <div className="brand-copy">
            <strong>KONTUR</strong>
            <span>3D по чертежу</span>
          </div>
          <button className="icon-button sidebar-collapse" type="button" aria-label="Свернуть панель">
            <Icon name="chevron" />
          </button>
        </div>

        <form className="side-form" onSubmit={submitDrawing}>
          <section className="panel-section upload-section">
            <div className="section-heading">
              <div>
                <span className="step-number">01</span>
                <h2>Чертёж</h2>
              </div>
              {file && (
                <button className="text-button" type="button" onClick={resetProject}>
                  Заменить
                </button>
              )}
            </div>

            <div
              className={`upload-drop ${file ? "has-file" : ""} ${dragging ? "is-dragging" : ""}`}
              onDragEnter={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => fileInput.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") fileInput.current?.click();
              }}
            >
              <input
                ref={fileInput}
                type="file"
                accept="image/png,image/jpeg"
                onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
              />
              {sourceUrl ? (
                <>
                  <img src={sourceUrl} alt="" />
                  <div className="upload-file-overlay">
                    <span className="file-type-badge">{file?.type === "image/png" ? "PNG" : "JPG"}</span>
                    <div>
                      <strong>{file?.name}</strong>
                      <small>{file ? formatBytes(file.size) : ""}</small>
                    </div>
                    <Icon name="check" />
                  </div>
                </>
              ) : (
                <div className="upload-empty">
                  <span className="upload-symbol"><Icon name="upload" /></span>
                  <strong>Перетащите чертёж</strong>
                  <small>или выберите PNG / JPG</small>
                  <span className="upload-limit">до 25 МБ</span>
                </div>
              )}
            </div>
          </section>

          <section className="panel-section">
            <div className="section-heading">
              <div>
                <span className="step-number">02</span>
                <h2>Параметры</h2>
              </div>
            </div>

            <label className="field-group">
              <span>Тип модели</span>
              <button className="select-control" type="button">
                <span className="select-leading"><Icon name="cube" /></span>
                <span><b>Отдельная деталь</b><small>Твердотельная модель</small></span>
                <Icon name="chevron" />
              </button>
            </label>

            <div className="field-group">
              <span>Материал</span>
              <div className="material-row">
                {materialOptions.map((option) => (
                  <button
                    className={material === option.value ? "active" : ""}
                    type="button"
                    key={option.value}
                    onClick={() => setMaterial(option.value)}
                    title={option.label}
                    aria-label={option.label}
                  >
                    <i style={{ background: option.color }} />
                    <span>{option.label}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="field-group">
              <span>Точность построения</span>
              <div className="segmented-control">
                <button
                  type="button"
                  className={precision === "standard" ? "active" : ""}
                  onClick={() => setPrecision("standard")}
                >
                  Стандартная
                </button>
                <button
                  type="button"
                  className={precision === "high" ? "active" : ""}
                  onClick={() => setPrecision("high")}
                >
                  Высокая
                </button>
              </div>
            </div>

            <div className="field-group">
              <span>Форматы результата</span>
              <div className="format-grid">
                {artifactOrder.slice(0, 3).map((type) => (
                  <label className={outputs[type] ? "selected" : ""} key={type}>
                    <input
                      type="checkbox"
                      checked={outputs[type]}
                      onChange={(event) =>
                        setOutputs((current) => ({ ...current, [type]: event.target.checked }))
                      }
                    />
                    <span>{type}</span>
                    <Icon name="check" />
                  </label>
                ))}
              </div>
            </div>
          </section>

          <section className="panel-section comment-section">
            <div className="section-heading">
              <div>
                <span className="step-number">03</span>
                <h2>Пожелания</h2>
              </div>
              <span className="counter">{comment.length}/1000</span>
            </div>
            <div className="textarea-wrap">
              <textarea
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                placeholder="Укажите важные особенности детали: сквозные отверстия, фаски, симметрию…"
                maxLength={1000}
              />
              <Icon name="sparkles" />
            </div>
          </section>

          <div className="form-footer">
            {error && <p className="error-message"><Icon name="info" />{error}</p>}
            <button className="primary-action" type="submit" disabled={busy}>
              <span>{busy ? "Обрабатываем…" : order ? "Построить заново" : "Создать 3D-модель"}</span>
              <Icon name={busy ? "refresh" : "arrow"} />
            </button>
            <p><Icon name="check" /> Размеры будут подтверждены перед построением</p>
          </div>
        </form>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="project-title">
            <span className="eyebrow">Новая модель</span>
            <div>
              <h1>{file ? cleanFileName(file.name) : "Деталь без названия"}</h1>
              {file && <span className="saved-state"><i /> Изменения сохранены</span>}
            </div>
          </div>
          <div className="topbar-actions">
            {file && (
              <button className="secondary-button" type="button" onClick={resetProject}>
                <Icon name="plus" /> Новая деталь
              </button>
            )}
            <span className={`status-pill status-${activeStatus.toLowerCase()}`}>
              <i />
              {statusCopy[activeStatus] ?? (file ? "Чертёж загружен" : "Готово к работе")}
            </span>
            <button className="avatar-button" type="button" aria-label="Профиль">К</button>
          </div>
        </header>

        <div className="workspace-body">
          <div className="viewer-card">
            <div className="viewer-toolbar">
              <div className="view-tabs">
                <button
                  className={viewMode === "model" ? "active" : ""}
                  type="button"
                  onClick={() => setViewMode("model")}
                >
                  <Icon name="cube" /> 3D-модель
                </button>
                <button
                  className={viewMode === "drawing" ? "active" : ""}
                  type="button"
                  disabled={!sourceUrl}
                  onClick={() => setViewMode("drawing")}
                >
                  <Icon name="image" /> Чертёж
                </button>
              </div>
              <div className="viewer-meta">
                <span>мм</span>
                <span className="meta-divider" />
                <span>{materialOptions.find((item) => item.value === material)?.label}</span>
              </div>
            </div>

            <div className="viewer-stage">
              {viewMode === "drawing" && sourceUrl ? (
                <div className="drawing-preview">
                  <img src={sourceUrl} alt="Загруженный технический чертёж" />
                  <div className="drawing-shadow" />
                </div>
              ) : (
                <StlPreview
                  url={stl ? `${API_URL}${stl.download_url}` : undefined}
                  token={token}
                  local={!token || !stl}
                  material={material}
                  dimensions={dimensions}
                  ready={order?.status === "READY"}
                />
              )}

              {/* An order opened by link has no local file, and the invitation
                  to upload one used to cover the finished model. */}
              {!file && !order && (
                <div className="viewer-welcome">
                  <span><Icon name="sparkles" /></span>
                  <h2>Превратите чертёж в точную 3D-модель</h2>
                  <p>Загрузите изображение — мы распознаем геометрию и подготовим файлы.</p>
                  <button type="button" onClick={() => fileInput.current?.click()}>
                    Выбрать чертёж <Icon name="arrow" />
                  </button>
                  <button type="button" className="ghost" onClick={useSampleDrawing}>
                    Попробовать на образце
                  </button>
                </div>
              )}

              {file && viewMode === "model" && order?.status !== "READY" && (
                <div className="model-state-card">
                  <span className={busy || working.has(order?.status ?? "") ? "pulse" : ""}>
                    <Icon name={order?.questions.length ? "settings" : "sparkles"} />
                  </span>
                  <div>
                    <strong>
                      {order?.questions.length
                        ? "Почти готово"
                        : working.has(order?.status ?? "")
                          ? "Создаём геометрию"
                          : "Чертёж готов к обработке"}
                    </strong>
                    <small>
                      {order?.questions.length
                        ? "Подтвердите размеры ниже"
                        : working.has(order?.status ?? "")
                          ? "Собираем объёмную модель"
                          : "Запустите построение в левой панели"}
                    </small>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/*
            An order that failed says so, with the reason.

            Until the worker could report a failure, this state was unreachable:
            a build that gave up left its job in PENDING, which reads as "waiting
            to start" — forever, and identical to a queue with no worker on it.
            The copy for FAILED has been in `statusCopy` all along with nothing
            able to select it.

            `waiting_reason` is shown for the same reason. The scheduler has been
            explaining why an order is stuck since POSTMVP-003A, into a field
            nothing rendered.
          */}
          {/*
            Unmistakable, and above everything else the order shows. A visitor
            with no token gets the flow and not a part, and the one thing that
            must never be ambiguous is which of the two they are looking at.
          */}
          {order && !token && (
            <div className="notice-card notice-demo" role="status">
              <span className="eyebrow">Демонстрация</span>
              <p>
                Чертёж <strong>не отправлялся</strong> и модель <strong>не строилась</strong>.
                Всё, что показано ниже, — пример того, как выглядит работа сервиса,
                а не ваша деталь. Скачивание отключено.
              </p>
            </div>
          )}

          {order?.status === "FAILED" && (
            <div className="notice-card notice-failed" role="alert">
              <span className="eyebrow">Не удалось построить</span>
              <p>{order.failure_message ?? "Сборка остановлена."}</p>
              {order.failure_code && <code>{order.failure_code}</code>}
              <p className="notice-hint">
                Чертёж сохранён. Загрузите его снова или уточните размеры — повторять
                автоматически мы уже пробовали.
              </p>
            </div>
          )}
          {order?.status === "PAUSED" && (
            <div className="notice-card notice-waiting">
              <span className="eyebrow">Заказ на паузе</span>
              <p>{order.failure_message ?? "Сервис временно не может обратиться к модели."}</p>
              {/*
                A pause is not a failure and not a queue. The order will build, and no
                worker can build it right now — an exhausted model quota is the case
                this exists for. Saying when we look again is the whole point: without
                it a pause is the same silence that "waiting to start" was.
              */}
              {order.retry_after && (
                <p className="notice-hint">
                  Попробуем снова{" "}
                  {new Date(order.retry_after).toLocaleString("ru-RU", {
                    hour: "2-digit", minute: "2-digit", day: "numeric", month: "long",
                  })}
                  . Ничего делать не нужно — чертёж сохранён.
                </p>
              )}
            </div>
          )}
          {order?.waiting_reason && order.status !== "FAILED" && order.status !== "PAUSED" && (
            <div className="notice-card notice-waiting">
              <span className="eyebrow">Заказ ждёт</span>
              <p>{order.waiting_reason}</p>
            </div>
          )}

          {order?.questions.length ? (
            <form className="clarification-card" onSubmit={submitAnswers}>
              <div className="clarification-intro">
                <span className="assistant-mark"><Icon name="sparkles" /></span>
                <div>
                  <span className="eyebrow">Уточнение размеров</span>
                  <h2>Подтвердите основные габариты</h2>
                  <p>Мы распознали значения на чертеже. Проверьте их перед построением.</p>
                </div>
              </div>
              <div className="question-row">
                {order.questions.map((question) => (
                  /*
                    Rendered from what the question says it wants.

                    Every question used to be a number field with a "мм" suffix,
                    and the reading stage has always been able to ask things that
                    are not numbers — "is this opening through or blind?". Those
                    had no answer this form could send and no answer the API would
                    accept, so the order stopped there permanently. A question
                    written before `answer_kind` existed is a number, which is
                    what all of them were.
                  */
                  question.answer_kind === "choice" ? (
                    <fieldset className="choice-field" key={question.id}>
                      <legend>{question.text}</legend>
                      {(question.choices ?? []).map((choice) => (
                        <label key={choice}>
                          <input
                            type="radio"
                            name={question.id}
                            value={choice}
                            checked={answers[question.id] === choice}
                            onChange={() =>
                              setAnswers((current) => ({ ...current, [question.id]: choice }))
                            }
                            required
                          />
                          <span>{choice}</span>
                        </label>
                      ))}
                    </fieldset>
                  ) : (
                    <label className="dimension-field" key={question.id}>
                      <span>{question.text}</span>
                      <div>
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
                      </div>
                    </label>
                  )
                ))}
                <button className="confirm-button" disabled={busy}>
                  <span>{busy ? "Создаём…" : "Подтвердить"}</span>
                  <Icon name={busy ? "refresh" : "arrow"} />
                </button>
              </div>
            </form>
          ) : (
            <div className="model-summary">
              <div className="summary-heading">
                <span className="summary-icon"><Icon name="box" /></span>
                <div>
                  <span className="eyebrow">{order?.status === "READY" ? "Геометрия подтверждена" : "Параметры модели"}</span>
                  <h2>{order?.status === "READY" ? "Деталь готова" : "Основные характеристики"}</h2>
                </div>
              </div>
              <div className="summary-metrics">
                <div>
                  <span>{measured ? "Габариты, измерено" : "Габариты"}</span>
                  <b>
                    {dimensions
                      ? `${dimensions.length} × ${dimensions.width} × ${dimensions.height} мм`
                      : "будут известны после построения"}
                  </b>
                </div>
                <div><span>Единицы</span><b>Миллиметры</b></div>
                <div><span>Качество</span><b>{precision === "high" ? "Высокое" : "Стандартное"}</b></div>
              </div>
            </div>
          )}
        </div>
      </section>

      <aside className="result-rail">
        <header className="result-header">
          <div>
            <span className="eyebrow">Результат</span>
            <h2>Готовые файлы</h2>
          </div>
          {order?.status === "READY" && <span className="ready-badge"><Icon name="check" /> Готово</span>}
        </header>

        <section className="progress-panel">
          <div className="progress-copy">
            <div>
              <strong>{statusCopy[activeStatus] ?? (file ? "Чертёж загружен" : "Новая модель")}</strong>
              <span>{progress === 100 ? "Все этапы завершены" : "Подготовка результата"}</span>
            </div>
            <b>{progress}%</b>
          </div>
          <div className="progress-track"><i style={{ width: `${progress}%` }} /></div>
        </section>

        <ol className="result-steps">
          <ProgressStep label="Чертёж загружен" active={Boolean(file)} complete={progress > 25} index="1" />
          <ProgressStep label="Геометрия распознана" active={progress >= 35} complete={progress > 55} index="2" />
          <ProgressStep label="Модель построена" active={progress >= 65} complete={progress > 85} index="3" />
          <ProgressStep label="Результат проверен" active={progress === 100} complete={progress === 100} index="4" last />
        </ol>

        <section className="files-panel">
          <div className="files-title">
            <h3>Файлы модели</h3>
            <span>{artifacts.length ? `${artifacts.length} файла` : "Пока пусто"}</span>
          </div>
          <div className="file-list">
            {artifactOrder.map((type) => {
              const artifact = artifacts.find((item) => item.type.toUpperCase() === type);
              const visible = outputs[type] ?? true;
              if (!visible) return null;
              return artifact ? (
                <button className="result-file ready" type="button" key={type} onClick={() => void download(artifact)}>
                  <span className={`result-file-icon file-${type.toLowerCase()}`}>
                    {type === "VALIDATION_REPORT" ? <Icon name="check" /> : type.slice(0, 2)}
                  </span>
                  <span>
                    <b>{artifactLabel(type)}</b>
                    <small>{artifactDescription(type)} · {formatBytes(artifact.size_bytes)}</small>
                  </span>
                  <span className="file-download"><Icon name="download" /></span>
                </button>
              ) : (
                <div className="result-file pending" key={type}>
                  <span className={`result-file-icon file-${type.toLowerCase()}`}>
                    {type === "VALIDATION_REPORT" ? <Icon name="check" /> : type.slice(0, 2)}
                  </span>
                  <span>
                    <b>{artifactLabel(type)}</b>
                    <small>{artifactDescription(type)}</small>
                  </span>
                  <span className="file-pending-dot" />
                </div>
              );
            })}
          </div>
        </section>

        {artifacts.length > 0 && (
          <button className="download-all" type="button" onClick={() => void downloadSelected()}>
            <Icon name="download" />
            <span>Скачать выбранные файлы</span>
          </button>
        )}

        <section className="quality-card">
          <span className="quality-icon"><Icon name="check" /></span>
          <div>
            <b>Геометрия под контролем</b>
            <p>Размеры, замкнутость модели и целостность файлов проверяются перед выдачей.</p>
          </div>
        </section>

        <footer className="result-footer">
          <span><i /> Сервис готов</span>
          <button type="button" aria-label="Настройки"><Icon name="settings" /></button>
        </footer>
      </aside>
    </main>
  );
}

function ProgressStep({
  label,
  active,
  complete,
  index,
  last = false,
}: {
  label: string;
  active: boolean;
  complete: boolean;
  index: string;
  last?: boolean;
}) {
  return (
    <li className={`${active ? "active" : ""} ${complete ? "complete" : ""}`}>
      <span className="step-marker">{complete ? <Icon name="check" /> : index}</span>
      <span>{label}</span>
      {!last && <i className="step-line" />}
    </li>
  );
}

function Logo() {
  return (
    <span className="logo-mark" aria-hidden="true">
      <svg viewBox="0 0 32 32" fill="none">
        <path d="M16 3.5 26.4 9.4v13.2L16 28.5 5.6 22.6V9.4L16 3.5Z" />
        <path d="m5.9 9.7 10.1 6 10.1-6M16 15.7v12.2" />
      </svg>
    </span>
  );
}

function Icon({ name }: { name: IconName }) {
  const common = { viewBox: "0 0 24 24", fill: "none", "aria-hidden": true };
  if (name === "check") return <svg {...common}><path d="m5 12.5 4.2 4.2L19 7" /></svg>;
  if (name === "arrow") return <svg {...common}><path d="M5 12h14m-5-5 5 5-5 5" /></svg>;
  if (name === "chevron") return <svg {...common}><path d="m9 6 6 6-6 6" /></svg>;
  if (name === "upload") return <svg {...common}><path d="M12 16V4m-5 5 5-5 5 5M5 15v4h14v-4" /></svg>;
  if (name === "download") return <svg {...common}><path d="M12 4v11m-4-4 4 4 4-4M5 19h14" /></svg>;
  if (name === "cube") return <svg {...common}><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Zm-7.6 4.7L12 12l7.6-4.3M12 12v9" /></svg>;
  if (name === "image") return <svg {...common}><rect x="3.5" y="4.5" width="17" height="15" rx="2" /><circle cx="9" cy="10" r="1.5" /><path d="m4.5 17 4.5-4 3.5 3 2.5-2 4.5 3.5" /></svg>;
  if (name === "sparkles") return <svg {...common}><path d="M12 3c.7 4.2 2.8 6.3 7 7-4.2.7-6.3 2.8-7 7-.7-4.2-2.8-6.3-7-7 4.2-.7 6.3-2.8 7-7Z" /><path d="M19 15.5c.3 1.8 1.2 2.7 3 3-1.8.3-2.7 1.2-3 3-.3-1.8-1.2-2.7-3-3 1.8-.3 2.7-1.2 3-3Z" /></svg>;
  if (name === "refresh") return <svg {...common} className="spin"><path d="M20 11a8 8 0 1 0-2.3 6M20 5v6h-6" /></svg>;
  if (name === "settings") return <svg {...common}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" /></svg>;
  if (name === "plus") return <svg {...common}><path d="M12 5v14M5 12h14" /></svg>;
  if (name === "box") return <svg {...common}><path d="M4 8.5 12 4l8 4.5v8L12 21l-8-4.5v-8Z" /><path d="m4.5 8.7 7.5 4.2 7.5-4.2M12 13v8" /></svg>;
  if (name === "info") return <svg {...common}><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></svg>;
  if (name === "trash") return <svg {...common}><path d="M5 7h14M9 7V4h6v3m2 0-1 13H8L7 7m3 4v5m4-5v5" /></svg>;
  if (name === "expand") return <svg {...common}><path d="M9 4H4v5m11-5h5v5M9 20H4v-5m11 5h5v-5" /></svg>;
  if (name === "layers") return <svg {...common}><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5M3 16l9 5 9-5" /></svg>;
  return <svg {...common}><path d="M6 3h9l4 4v14H6V3Z" /><path d="M15 3v5h5" /></svg>;
}

function artifactLabel(type: string) {
  return {
    STEP: "STEP-модель",
    STL: "STL-модель",
    VALIDATION_REPORT: "Паспорт модели",
  }[type] ?? type;
}

function artifactDescription(type: string) {
  return {
    STEP: "Для CAD-систем",
    STL: "Для производства",
    VALIDATION_REPORT: "Результаты проверки",
  }[type] ?? "Файл модели";
}

function localArtifacts(): Artifact[] {
  return artifactOrder.map((type) => ({
    type,
    size_bytes: new TextEncoder().encode(localArtifactContents(type)).byteLength,
    sha256: "LOCAL",
    download_url: `/result/${type.toLowerCase()}`,
  }));
}

function localArtifactContents(type: string) {
  if (type === "STL") return LOCAL_STL;
  if (type === "STEP") return "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('KONTUR 3D MODEL'),'2;1');\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n";
  return JSON.stringify({ valid: true, body_count: 1, units: "mm", dimensions: [80, 40, 12] }, null, 2);
}

const LOCAL_STL = `solid kontur
  facet normal 0 0 -1
    outer loop
      vertex -40 -20 0
      vertex 40 -20 0
      vertex 40 20 0
    endloop
  endfacet
  facet normal 0 0 -1
    outer loop
      vertex -40 -20 0
      vertex 40 20 0
      vertex -40 20 0
    endloop
  endfacet
  facet normal 0 0 1
    outer loop
      vertex -40 -20 12
      vertex 40 20 12
      vertex 40 -20 12
    endloop
  endfacet
  facet normal 0 0 1
    outer loop
      vertex -40 -20 12
      vertex -40 20 12
      vertex 40 20 12
    endloop
  endfacet
  facet normal -1 0 0
    outer loop
      vertex -40 -20 0
      vertex -40 20 0
      vertex -40 20 12
    endloop
  endfacet
  facet normal -1 0 0
    outer loop
      vertex -40 -20 0
      vertex -40 20 12
      vertex -40 -20 12
    endloop
  endfacet
  facet normal 1 0 0
    outer loop
      vertex 40 -20 0
      vertex 40 -20 12
      vertex 40 20 12
    endloop
  endfacet
  facet normal 1 0 0
    outer loop
      vertex 40 -20 0
      vertex 40 20 12
      vertex 40 20 0
    endloop
  endfacet
  facet normal 0 -1 0
    outer loop
      vertex -40 -20 0
      vertex -40 -20 12
      vertex 40 -20 12
    endloop
  endfacet
  facet normal 0 -1 0
    outer loop
      vertex -40 -20 0
      vertex 40 -20 12
      vertex 40 -20 0
    endloop
  endfacet
  facet normal 0 1 0
    outer loop
      vertex -40 20 0
      vertex 40 20 0
      vertex 40 20 12
    endloop
  endfacet
  facet normal 0 1 0
    outer loop
      vertex -40 20 0
      vertex 40 20 12
      vertex -40 20 12
    endloop
  endfacet
endsolid kontur`;

function mediaTypeFor(type: string) {
  return type === "VALIDATION_REPORT" ? "application/json" : "application/octet-stream";
}

function triggerDownload(blob: Blob, filename: string) {
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function extensionFor(type: string) {
  return ({ STEP: "step", STL: "stl", VALIDATION_REPORT: "json" } as Record<string, string>)[type] ?? "bin";
}

function cleanFileName(value: string) {
  return value.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
}

/**
 * The measured bounding box out of a validation report, or nothing.
 *
 * The report is written by the worker and owned there, so this reads it
 * defensively: a shape it does not recognise produces null and the page shows no
 * dimensions, which is the correct answer when it does not know them.
 */
function readBoundingBox(report: unknown): Dimensions | null {
  const box = (report as { geometry?: { Mesh?: { BoundingBox?: unknown } } })?.geometry?.Mesh
    ?.BoundingBox;
  if (!Array.isArray(box) || box.length < 3) return null;
  const [length, width, height] = box.slice(0, 3).map(Number);
  if (![length, width, height].every((value) => Number.isFinite(value) && value > 0)) return null;
  // Two decimals: the mesh is a tessellation, so more digits would claim a
  // precision the measurement does not have.
  const round = (value: number) => Number(value.toFixed(2));
  return { length: round(length), width: round(width), height: round(height) };
}

function getProgress(status: string) {
  return {
    EMPTY: 0,
    DRAFT: 18,
    WAITING_FOR_LOCAL_WORKER: 30,
    DRAWING_ANALYSIS: 52,
    WAITING_FOR_USER_ANSWERS: 46,
    CAD_BUILDING: 68,
    CAD_VALIDATION: 84,
    READY: 100,
    FAILED: 62,
    PAUSED: 30,
    MANUAL_REVIEW: 62,
  }[status] ?? 0;
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} Б`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} КБ`;
  return `${(value / (1024 * 1024)).toFixed(1)} МБ`;
}

function message(reason: unknown) {
  return reason instanceof Error ? reason.message : "Не удалось выполнить действие.";
}

async function safeError(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    return typeof payload.detail === "string" ? payload.detail : `Не удалось выполнить запрос (${response.status})`;
  } catch {
    return `Не удалось выполнить запрос (${response.status})`;
  }
}

function delay(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
