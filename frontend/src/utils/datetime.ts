// Every timestamp the backend sends is UTC (see backend/utils/time.py's `utcnow()`), but
// Pydantic serializes a naive `datetime` with NO timezone suffix — e.g. "2026-08-18T10:00:00",
// not "...Z" or "...+00:00". Per the ECMAScript spec, `new Date(...)` on an ISO string with a
// "T" but no timezone designator is parsed as LOCAL time, not UTC. In a browser set to
// UTC+7 (Vietnam), that silently shifts every timestamp 7 hours off — small enough to go
// unnoticed on a clock reading, but glaring on a computed "N minutes ago".
//
// Fix at the one place every other date-parsing call site in this app should go through,
// rather than special-casing each one: append "Z" when the string has no timezone info of
// its own, then hand it to `new Date()` as usual.
export function parseServerDate(iso: string): Date {
  const hasTimezone = /Z$|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasTimezone ? iso : `${iso}Z`);
}
