import { api } from "./client";

export type PlanId = "starter" | "growth" | "enterprise";

/** One row of the published pricing table, served by the backend so the marketing page
 *  and the biller can never quote different numbers. */
export interface Plan {
  id: PlanId;
  name: string;
  description: string | null;
  price_per_seat_vnd: number;
  min_seats: number;
  /** null means no hard cap (Enterprise) — render as "không giới hạn cứng", not 0. */
  conversations_per_seat: number | null;
  overage_price_vnd: number;
  support_note: string | null;
  sort_order: number;
}

export interface Quote {
  plan_id: PlanId;
  plan_name: string;
  seats: number;
  price_per_seat_vnd: number;
  monthly_total_vnd: number;
  included_conversations: number | null;
  overage_price_vnd: number;
}

export interface SubscriptionRequestPayload {
  plan_id: PlanId;
  seats: number;
  company_name: string;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  password: string;
  tax_code?: string | null;
  billing_address?: string | null;
  note?: string | null;
}

export interface SubscriptionRequestResult {
  id: number;
  plan_id: PlanId;
  seats: number;
  company_name: string;
  contact_email: string;
  quoted_monthly_total_vnd: number;
  status: "pending" | "contacted" | "approved" | "rejected";
  created_at: string;
}

export const billingApi = {
  listPlans: () => api.get<Plan[]>("/billing/plans"),

  /** Priced by the backend rather than multiplied in the browser, so the total on the
   *  confirmation screen is the one that gets stored on the request. */
  quote: (planId: PlanId, seats: number) =>
    api.get<Quote>(`/billing/quote?plan_id=${encodeURIComponent(planId)}&seats=${seats}`),

  submitRequest: (payload: SubscriptionRequestPayload) =>
    api.post<SubscriptionRequestResult>("/billing/subscription-requests", payload),
};

/** VND with thin separators, e.g. 2.750.000đ — the format the pricing page already uses. */
export function formatVnd(amount: number): string {
  return `${amount.toLocaleString("vi-VN")}đ`;
}
