"use client";

/**
 * The moderation queue, for the two roles that may see everybody's drawings.
 *
 * A route of its own rather than a panel on the studio page, because the two are
 * different jobs done by different people: a customer looks at one order and an
 * operator looks at the list of everything waiting. The role gate is enforced by
 * the API — every endpoint below answers 404 to a customer — and this page's own
 * check is only so that somebody who wanders here is told why it is empty rather
 * than watching a spinner.
 */

import { FormEvent, useCallback, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Session = { user_id: string; email: string; role: string; csrf_token: string };
type QueuedOrder = {
  order_id: string;
  status: string;
  version: number;
  owner_id: string | null;
  latest_job_id: string | null;
  clarification_round: number;
  created_at: string | null;
  updated_at: string;
};
type Review = {
  id: string;
  decision: string;
  reason: string | null;
  reviewer_id: string | null;
  order_version_before: number;
  order_status_after: string;
  created_at: string;
};
type Artifact = { type: string; size_bytes: number; sha256: string; download_url: string };
type Decision = "approve" | "reject" | "request_changes";

const decisionLabel: Record<Decision, string> = {
  approve: "Одобрить",
  reject: "Отклонить",
  request_changes: "Вернуть на доработку",
};

export default function OperatorQueue() {
  const [session, setSession] = useState<Session | null>(null);
  const [checked, setChecked] = useState(false);
  const [orders, setOrders] = useState<QueuedOrder[]>([]);
  const [total, setTotal] = useState(0);
  const [openOrder, setOpenOrder] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const api = useCallback(
    (path: string, init: RequestInit = {}) => {
      const headers = new Headers(init.headers);
      if (session) headers.set("x-csrf-token", session.csrf_token);
      return fetch(`${API_URL}${path}`, { ...init, headers, credentials: "include" });
    },
    [session],
  );

  useEffect(() => {
    void (async () => {
      try {
        const response = await fetch(`${API_URL}/api/v1/auth/me`, {
          credentials: "include",
          cache: "no-store",
        });
        if (response.ok) setSession((await response.json()) as Session);
      } catch {
        // Not signed in, or the API is down. Both end on the same screen.
      } finally {
        setChecked(true);
      }
    })();
  }, []);

  const staff = session !== null && session.role !== "customer";

  const loadQueue = useCallback(async () => {
    if (!staff) return;
    try {
      const response = await api("/api/v1/operator/orders?limit=50");
      if (!response.ok) throw new Error(await safeError(response));
      const page = await response.json();
      setOrders(page.orders as QueuedOrder[]);
      setTotal(page.total as number);
      setError("");
    } catch (reason_) {
      setError(message(reason_));
    }
  }, [api, staff]);

  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  async function open(order: QueuedOrder) {
    setOpenOrder(order.order_id);
    setReason("");
    setArtifacts([]);
    setReviews([]);
    try {
      // What the operator is actually deciding about: the files, and whatever has
      // already been decided about this order. A queue that shows only ids is one
      // where every decision is made on faith.
      const [job, trail] = await Promise.all([
        api(`/api/v1/drawing-jobs/${order.order_id}`, { cache: "no-store" }),
        api(`/api/v1/operator/orders/${order.order_id}/reviews`, { cache: "no-store" }),
      ]);
      if (job.ok) setArtifacts(((await job.json()).artifacts ?? []) as Artifact[]);
      if (trail.ok) setReviews((await trail.json()) as Review[]);
    } catch (reason_) {
      setError(message(reason_));
    }
  }

  async function decide(order: QueuedOrder, decision: Decision, event: FormEvent) {
    event.preventDefault();
    if (decision !== "approve" && !reason.trim()) {
      setError("Отказ и возврат на доработку требуют причины.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await api(`/api/v1/operator/orders/${order.order_id}/review`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          decision,
          // The version the operator was looking at, not "whatever it is now".
          // If somebody else decided while this page was open, the API refuses
          // with ORDER_VERSION_CONFLICT instead of quietly overwriting them.
          expected_version: order.version,
          ...(reason.trim() ? { reason: reason.trim() } : {}),
        }),
      });
      if (!response.ok) throw new Error(await safeError(response));
      setOpenOrder(null);
      await loadQueue();
    } catch (reason_) {
      setError(message(reason_));
    } finally {
      setBusy(false);
    }
  }

  async function download(artifact: Artifact) {
    setError("");
    try {
      const response = await api(artifact.download_url);
      if (!response.ok) throw new Error(await safeError(response));
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `order.${artifact.type.toLowerCase()}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (reason_) {
      setError(message(reason_));
    }
  }

  if (!checked) return <main className="operator-page"><p>Загрузка…</p></main>;
  if (!staff) {
    return (
      <main className="operator-page">
        <h1>Очередь модерации</h1>
        <p className="auth-hint">
          Эта страница — для оператора. Войдите учётной записью с ролью operator или
          admin: у неё есть второй фактор, и это не случайность — такой аккаунт видит
          чертежи всех заказчиков.
        </p>
      </main>
    );
  }

  return (
    <main className="operator-page">
      <header className="operator-head">
        <h1>Очередь модерации</h1>
        <span className="account-email">
          {session?.email} · {session?.role}
        </span>
      </header>
      <p className="auth-hint">
        Заказов ждёт решения: <strong>{total}</strong>. Старые сверху — заказчик,
        который ждёт дольше всех, не должен оказаться последним в списке.
      </p>
      {error && <div className="notice-card notice-failed" role="alert"><p>{error}</p></div>}

      {orders.length === 0 && <p className="auth-hint">Пока ничего не ждёт.</p>}

      <ul className="queue-list">
        {orders.map((order) => (
          <li key={order.order_id} className="queue-item">
            <button type="button" className="queue-row" onClick={() => void open(order)}>
              <code>{order.order_id.slice(0, 8)}</code>
              <span>{new Date(order.updated_at).toLocaleString("ru-RU")}</span>
              <span>раунд {order.clarification_round}</span>
              <span>{order.owner_id ? "есть владелец" : "без владельца"}</span>
            </button>

            {openOrder === order.order_id && (
              <form className="queue-detail" onSubmit={(event) => void decide(order, "approve", event)}>
                <div className="queue-artifacts">
                  {artifacts.length === 0 && <span className="auth-hint">Файлы не найдены.</span>}
                  {artifacts.map((artifact) => (
                    <button
                      key={artifact.type}
                      type="button"
                      className="secondary-button"
                      onClick={() => void download(artifact)}
                    >
                      {artifact.type} · {Math.round(artifact.size_bytes / 1024)} КБ
                    </button>
                  ))}
                </div>

                {reviews.length > 0 && (
                  <ul className="queue-history">
                    {reviews.map((review) => (
                      <li key={review.id}>
                        <strong>{decisionLabel[review.decision as Decision] ?? review.decision}</strong>
                        {" · "}
                        {new Date(review.created_at).toLocaleString("ru-RU")}
                        {review.reason && <> · {review.reason}</>}
                      </li>
                    ))}
                  </ul>
                )}

                <label className="queue-reason">
                  <span>
                    Причина <em>(обязательна для отказа и возврата)</em>
                  </span>
                  <textarea
                    rows={3}
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                  />
                </label>

                <div className="queue-actions">
                  <button className="primary-button" type="submit" disabled={busy}>
                    {decisionLabel.approve}
                  </button>
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={busy}
                    onClick={(event) => void decide(order, "request_changes", event)}
                  >
                    {decisionLabel.request_changes}
                  </button>
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={busy}
                    onClick={(event) => void decide(order, "reject", event)}
                  >
                    {decisionLabel.reject}
                  </button>
                </div>
              </form>
            )}
          </li>
        ))}
      </ul>
    </main>
  );
}

async function safeError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    if (typeof body?.message === "string") return body.message;
  } catch {
    // A body that is not JSON says nothing useful; the status does.
  }
  return `Ошибка ${response.status}`;
}

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : "Что-то пошло не так.";
}
