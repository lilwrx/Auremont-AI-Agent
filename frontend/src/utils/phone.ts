// Mirrors backend/utils/phone.py so a visitor sees the problem inline instead of being
// bounced by a 422 on a field they were mid-way through typing. The server still
// normalises and validates — this is a courtesy, never the authority.

const VN_MOBILE = /^0[35789]\d{8}$/;

/** Strip separators and map +84/84 to the leading 0. Returns "" for blank input. */
export function normalisePhone(raw: string): string {
  const digits = raw.replace(/[\s.\-()]+/g, "");
  if (!digits) return "";
  if (digits.startsWith("+84")) return `0${digits.slice(3)}`;
  if (digits.startsWith("84") && digits.length === 11) return `0${digits.slice(2)}`;
  return digits;
}

export function isValidPhone(raw: string): boolean {
  return VN_MOBILE.test(normalisePhone(raw));
}

export const PHONE_ERROR = "Số điện thoại không hợp lệ (VD: 0912345678)";
