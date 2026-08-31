// FastAPI's error body shape differs by failure kind: a raised HTTPException gives
// `{"detail": "some string"}`, but a 422 Pydantic validation error gives
// `{"detail": [{"loc": [...], "msg": "some string", "type": "..."}, ...]}` — an ARRAY.
// Passing that array straight into `new Error(message)` stringifies it via Array.toString(),
// which calls each object's default toString() and produces the literal text
// "[object Object]" — exactly the confusing message this extracts a real one instead of.
export function extractErrorMessage(body: unknown, fallback: string): string {
  if (typeof body !== "object" || body === null) return fallback;
  const detail = (body as { detail?: unknown }).detail;

  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => (entry && typeof entry === "object" && "msg" in entry ? String((entry as { msg: unknown }).msg) : null))
      .filter((msg): msg is string => Boolean(msg));
    if (messages.length > 0) return messages.join("; ");
  }

  return fallback;
}
