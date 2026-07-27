/* Generated from schemas/openapi.v1.json. Do not add unversioned endpoints here. */
export type OrderStatus =
  | "DRAFT" | "UPLOADED" | "INPUT_VALIDATION" | "WAITING_FOR_LOCAL_WORKER"
  | "DRAWING_ANALYSIS" | "WAITING_FOR_USER_ANSWERS" | "PLAN_READY"
  | "WAITING_FOR_PLAN_APPROVAL" | "QUEUED_FOR_CAD" | "CAD_BUILDING"
  | "CAD_VALIDATION" | "AUTO_REPAIR" | "READY" | "MANUAL_REVIEW"
  | "FAILED" | "CANCELLED" | "EXPIRED";

export interface TransitionOrderRequest { expected_version: number; target_status: OrderStatus; reason?: string | null; }
export interface OrderSnapshot { id: string; status: OrderStatus; version: number; updated_at: string; }
export interface WorkerClaimRequest { protocol_version: "1.0"; worker_id: string; capabilities: ("AI_DRAWING" | "KOMPAS_BUILD")[]; supported_cad_ir: string[]; available_slots: number; }

export class CadAiApiClient {
  constructor(private readonly baseUrl: string, private readonly fetchImpl: typeof fetch = fetch) {}
  async transitionOrder(orderId: string, request: TransitionOrderRequest): Promise<OrderSnapshot> {
    const response = await this.fetchImpl(`${this.baseUrl}/api/v1/orders/${orderId}/transition`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(request) });
    if (!response.ok) throw new Error(`Order transition failed: ${response.status}`);
    return response.json() as Promise<OrderSnapshot>;
  }
}
