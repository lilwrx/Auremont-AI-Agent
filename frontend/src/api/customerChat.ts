// Dedicated fetch wrapper for the public/customer chat endpoints (backend/routers/customer_chat.py).
//
// Kept separate from api/client.ts rather than folded into it: that client always attaches
// the Sale/Admin/Customer `Authorization` header from `access_token` and nothing else, while
// this flow must also work for a visitor with no account at all — those calls carry an
// `X-Visitor-Token` header instead, sourced from useVisitorToken's localStorage cache. Mixing
// both header schemes into the generic client used everywhere else in the app would make the
// common case harder to reason about for no benefit.

import { getVisitorSession } from "../hooks/useVisitorToken";
import { extractErrorMessage } from "./errorMessage";

const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";

export class CustomerApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function isAuthenticatedCustomer(): boolean {
  return Boolean(localStorage.getItem("access_token")) && localStorage.getItem("role") === "customer";
}

function authHeaders(): HeadersInit {
  const token = localStorage.getItem("access_token");
  if (isAuthenticatedCustomer()) return { Authorization: `Bearer ${token}` };

  const visitor = getVisitorSession();
  return visitor ? { "X-Visitor-Token": visitor.visitorToken } : {};
}

function buildHeaders(options: RequestInit): Headers {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  for (const [key, value] of Object.entries(authHeaders())) headers.set(key, value);
  return headers;
}

// Same silent-refresh-and-retry-once pattern as api/client.ts, duplicated rather than shared
// (see the file-level comment above on why this client stays separate) — an access token
// expiring mid-conversation must not surface as a failed send. Only reachable for a logged-in
// customer: an anonymous visitor has no tokens to refresh, so a 401 there falls straight
// through to a real failure.
let refreshInFlight: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = localStorage.getItem("refresh_token");
  if (!refreshToken) return false;

  const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  }).catch(() => null);

  if (!response?.ok) return false;

  const data = (await response.json()) as { access_token: string; refresh_token: string };
  localStorage.setItem("access_token", data.access_token);
  localStorage.setItem("refresh_token", data.refresh_token);
  return true;
}

/** Both tokens are dead — drop them so the header falls back to whatever visitor cache (if
 * any) exists, instead of keeping stale credentials around that would just 401 again. */
function clearCustomerSession(): void {
  ["access_token", "refresh_token", "role", "username"].forEach((k) => localStorage.removeItem(k));
}

async function customerFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers: buildHeaders(options) });

  if (response.status === 401 && isAuthenticatedCustomer()) {
    refreshInFlight ??= refreshAccessToken().finally(() => {
      refreshInFlight = null;
    });

    if (await refreshInFlight) {
      response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers: buildHeaders(options) });
    } else {
      clearCustomerSession();
    }
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new CustomerApiError(response.status, extractErrorMessage(body, response.statusText || "Request failed"));
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const customerApi = {
  get: <T>(path: string) => customerFetch<T>(path),
  post: <T>(path: string, body?: unknown) =>
    customerFetch<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => customerFetch<T>(path, { method: "DELETE" }),
};
