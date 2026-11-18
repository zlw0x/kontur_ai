"use client";

import { useEffect, useRef, useState } from "react";

type Api = (path: string, init?: RequestInit) => Promise<Response>;
type Parameter = { id: string; name?: string; type: string; unit?: string; value: number };
type Project = {
  id: string; name: string; revision: number; status: string; order_id?: string;
  failure_message?: string;
  cad_ir: { parameters: Parameter[] };
  versions: { revision: number; created_at: string; order_id: string }[];
};
type Summary = { id: string; name: string; revision: number };

const statusNames: Record<string, string> = {
  READY: "Изменения проверены и сохранены",
  FAILED: "Версия не прошла проверку. Можно восстановить предыдущую",
  DISPATCH_PENDING: "Проект сохранён, сборку нужно отправить повторно",
  MANUAL_REVIEW: "Модель построена и ожидает проверки инженером",
  PAUSED: "Сборка приостановлена",
};

async function checked(response: Response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : "Не удалось выполнить действие. Проверьте введённые размеры.");
  }
  return response.json();
}

export default function ProjectEditor({ api, authed, sourceOrderId, sourceReady, onVersion, resetSignal }: {
  api: Api; authed: boolean; sourceOrderId: string | null; sourceReady: boolean;
  onVersion: (orderId: string) => void; resetSignal: number;
}) {
  const services = useRef({ api, onVersion });
  services.current = { api, onVersion };
  const [project, setProject] = useState<Project | null>(null);
  const [models, setModels] = useState<Summary[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [text, setText] = useState("");
  const [hole, setHole] = useState({ diameter: "6", x: "0", y: "0" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);

  function accept(next: Project) {
    setProject(next);
    setValues(Object.fromEntries(next.cad_ir.parameters.map(p => [p.id, String(p.value)])));
    const order = next.versions.find(v => v.revision === next.revision)?.order_id;
    if (order) services.current.onVersion(order);
    window.history.replaceState(null, "", `?project=${next.id}`);
  }

  async function refreshList() {
    const list = await checked(await services.current.api("/api/v1/projects"));
    setModels(list as Summary[]);
  }

  useEffect(() => {
    generation.current++;
    setProject(null);
    setError("");
  }, [resetSignal]);

  useEffect(() => {
    const current = ++generation.current;
    setProject(null);
    setModels([]);
    if (!authed) return;
    void (async () => {
      try {
        const list = await checked(await services.current.api("/api/v1/projects"));
        if (generation.current !== current) return;
        setModels(list as Summary[]);
        const id = new URLSearchParams(window.location.search).get("project");
        if (id) {
          const next = await checked(await services.current.api(`/api/v1/projects/${encodeURIComponent(id)}`));
          if (generation.current === current) accept(next as Project);
        }
      } catch (reason) {
        if (generation.current === current) setError(reason instanceof Error ? reason.message : "Не удалось открыть проекты.");
      }
    })();
  }, [authed]);

  useEffect(() => {
    if (!project || ["READY", "FAILED", "DISPATCH_PENDING"].includes(project.status)) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const next = await checked(await services.current.api(`/api/v1/projects/${project.id}`, { cache: "no-store" }));
          if (!cancelled) {
            // Polling must not overwrite a number somebody is currently typing.
            setProject(next as Project);
          }
        } catch (reason) {
          if (!cancelled) setError(reason instanceof Error ? reason.message : "Не удалось проверить сборку.");
        }
      })();
    }, project.status === "PAUSED" ? 60_000 : 3_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [project?.id, project?.revision, project?.status]);

  async function run(action: () => Promise<Project>) {
    setBusy(true);
    setError("");
    const current = ++generation.current;
    try {
      const next = await action();
      if (current === generation.current) {
        accept(next);
        await refreshList();
      }
    } catch (reason) {
      if (current === generation.current) setError(reason instanceof Error ? reason.message : "Не удалось сохранить правку.");
    } finally {
      setBusy(false);
    }
  }

  function create(source: "enclosure" | "order") {
    void run(async () => checked(await api("/api/v1/projects", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(source === "order"
        ? { name: "Моя деталь", source_order_id: sourceOrderId }
        : { name: "Корпус", enclosure: { width: 120, height: 80, depth: 40, wall: 3 } }),
    })) as Promise<Project>);
  }

  function edit(operation: Record<string, unknown>) {
    if (!project) return;
    void run(async () => checked(await api(`/api/v1/projects/${project.id}/edits`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...operation, expected_revision: project.revision, action_id: crypto.randomUUID() }),
    })) as Promise<Project>);
  }

  async function downloadDocument() {
    if (!project) return;
    try {
      const response = await api(`/api/v1/projects/${project.id}/cad-ir`);
      if (!response.ok) throw new Error("Не удалось скачать проект.");
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = `kontur-${project.id}-v${project.revision}.cad-ir.json`; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Ошибка скачивания."); }
  }

  const ready = project?.status === "READY" && !busy;
  return <section className="project-editor" aria-label="Редактирование и мои модели" onKeyDown={event => {
    if (event.key === "Enter" && event.target instanceof HTMLInputElement && event.target.type === "number") event.preventDefault();
  }}>
    <div className="section-heading"><h2>Мои модели</h2></div>
    {!authed ? <p>Войдите, чтобы сохранять модели и изменять размеры.</p> : <>
      <label className="field-group"><span>Открыть сохранённую модель</span>
        <select aria-label="Мои модели" value={project?.id ?? ""} disabled={busy} onChange={event => {
          const id = event.target.value;
          if (id) void run(async () => checked(await api(`/api/v1/projects/${id}`)) as Promise<Project>);
        }}><option value="">Выберите модель</option>{models.map(model => <option key={model.id} value={model.id}>{model.name} · v{model.revision}</option>)}</select>
      </label>
      <div className="editor-actions">
        <button type="button" disabled={busy} onClick={() => create("enclosure")}>Новый корпус</button>
        {sourceReady && sourceOrderId && !project && <button type="button" disabled={busy} onClick={() => create("order")}>Сохранить и редактировать деталь</button>}
      </div>
      {project && <>
        <p className="editor-state" role="status">{project.name} · версия {project.revision}<br />{statusNames[project.status] ?? "Перестраиваем модель и проверяем размеры…"}</p>
        {project.failure_message && <p className="error-message">{project.failure_message}</p>}
        {project.status === "DISPATCH_PENDING" && <button type="button" disabled={busy} onClick={() => {
          void run(async () => checked(await api(`/api/v1/projects/${project.id}/retry-build`, { method: "POST" })) as Promise<Project>);
        }}>Повторить отправку сборки</button>}
        {project.cad_ir.parameters.filter(p => p.type === "length").map(parameter => <div className="editor-parameter" key={parameter.id}>
          <label htmlFor={`parameter-${parameter.id}`}>{parameter.name ?? parameter.id}, мм</label>
          <div className="editor-value">
            <input id={`parameter-${parameter.id}`} type="number" min="0.01" max="2000" step="0.1" disabled={!ready}
              value={values[parameter.id] ?? ""} onChange={event => setValues(v => ({ ...v, [parameter.id]: event.target.value }))} />
            <button type="button" disabled={!ready || !Number.isFinite(Number(values[parameter.id])) || Number(values[parameter.id]) <= 0 || Number(values[parameter.id]) === parameter.value}
              onClick={() => edit({ kind: "parameters", changes: { [parameter.id]: Number(values[parameter.id]) } })}>Применить</button>
          </div>
          <input type="range" aria-label={`${parameter.name ?? parameter.id}: ползунок`} min="0.1" max={Math.min(2000, Math.max(100, parameter.value * 2))} step="0.1"
            disabled={!ready} value={Number(values[parameter.id]) || parameter.value}
            onChange={event => setValues(v => ({ ...v, [parameter.id]: event.target.value }))} />
        </div>)}
        <label className="field-group"><span>Изменить словами</span>
          <input value={text} disabled={!ready} onChange={event => setText(event.target.value)} maxLength={300}
            placeholder="увеличь ширину на 10" onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); if (ready && text.trim()) edit({ kind: "text", text }); } }} />
        </label>
        <button type="button" disabled={!ready || !text.trim()} onClick={() => edit({ kind: "text", text })}>Выполнить правку</button>
        <small>Команды: «ширина 140», «увеличь ширину на 10». Для других размеров используйте имя из списка.</small>
        <details><summary>Добавить сквозное отверстие</summary>
          <p>Координаты от центра корпуса, в дне. Отверстие проверяется после сборки.</p>
          {(["diameter", "x", "y"] as const).map(key => <label className="field-group" key={key}>
            <span>{key === "diameter" ? "Диаметр, мм" : `${key.toUpperCase()} от центра, мм`}</span>
            <input type="number" value={hole[key]} disabled={!ready} step="0.1" min={key === "diameter" ? "0.1" : "-2000"} max="2000"
              onChange={event => setHole(h => ({ ...h, [key]: event.target.value }))} />
          </label>)}
          <button type="button" disabled={!ready || !Object.values(hole).every(v => v.trim() && Number.isFinite(Number(v))) || Number(hole.diameter) <= 0}
            onClick={() => edit({ kind: "hole", diameter: Number(hole.diameter), x: Number(hole.x), y: Number(hole.y) })}>Добавить отверстие</button>
        </details>
        <details><summary>История версий и отмена</summary>
          <p>Восстановление создаёт новую версию и сохраняет всю историю.</p>
          {project.versions.map(version => <div className="editor-version" key={version.revision}>
            <span>v{version.revision} · {new Date(version.created_at).toLocaleString("ru-RU")}</span>
            <button type="button" disabled={busy || version.revision === project.revision}
              onClick={() => edit({ kind: "restore", revision: version.revision })}>Восстановить</button>
          </div>)}
        </details>
        <button type="button" disabled={busy} onClick={() => void downloadDocument()}>Скачать редактируемый проект</button>
      </>}
      {error && <p className="error-message" role="alert">{error}</p>}
    </>}
  </section>;
}
