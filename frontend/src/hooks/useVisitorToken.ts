const SESSION_KEY = "customer_visitor_session_id";
const TOKEN_KEY = "customer_visitor_token";

/** The anonymous customer-chat session cached in this browser, if any.
 *
 * Both values always originate from the backend's `POST /customer/sessions/anonymous`
 * response (see api/customerChat.ts) — never generated client-side — so the token stays
 * opaque and cannot be guessed/forged into reading someone else's session.
 */
export function getVisitorSession(): { sessionId: number; visitorToken: string } | null {
  const sessionId = localStorage.getItem(SESSION_KEY);
  const visitorToken = localStorage.getItem(TOKEN_KEY);
  if (!sessionId || !visitorToken) return null;
  return { sessionId: Number(sessionId), visitorToken };
}

export function setVisitorSession(sessionId: number, visitorToken: string): void {
  localStorage.setItem(SESSION_KEY, String(sessionId));
  localStorage.setItem(TOKEN_KEY, visitorToken);
}

/** Called once the visitor registers/logs in and the session is claimed server-side —
 * it now belongs to their account, so the anonymous cache must not keep being used. */
export function clearVisitorSession(): void {
  localStorage.removeItem(SESSION_KEY);
  localStorage.removeItem(TOKEN_KEY);
}
