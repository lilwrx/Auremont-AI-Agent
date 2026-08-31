const FILE_EXTENSION = /\.(pdf|docx)$/i;
const STORAGE_PREFIX = /^(?:[a-f\d]{32,64}|[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12})[-_]+/i;

const VIETNAMESE_DOCUMENT_PHRASES: Array<[RegExp, string]> = [
  [/\bBang Gia\b/gi, "Bảng giá"],
  [/\bChinh Sach Ban Hang\b/gi, "Chính sách bán hàng"],
  [/\bTai Lieu\b/gi, "Tài liệu"],
  [/\bQuy Dinh\b/gi, "Quy định"],
  [/\bXung Dot\b/gi, "xung đột"],
  [/\bThong Tin Du An\b/gi, "Thông tin dự án"],
  [/\bTien Do Thanh Toan\b/gi, "Tiến độ thanh toán"],
  [/\bMat Bang\b/gi, "Mặt bằng"],
  [/\bPhap Ly\b/gi, "Pháp lý"],
  [/\bSao Bien\b/gi, "Sao Biển"],
  [/\bSan Ho\b/gi, "San Hô"],
  [/\bHai Au\b/gi, "Hải Âu"],
  [/\bNgoc Trai\b/gi, "Ngọc Trai"],
  [/\bdot(?=\s*\d)\b/gi, "đợt"],
];

export interface DocumentDisplayName {
  name: string;
  extension: string | null;
}

/**
 * Turns storage-oriented upload names into a readable label without mutating the
 * original document title kept by the backend for audit and object-store lookup.
 */
export function getDocumentDisplayName(title: string): DocumentDisplayName {
  const source = title.trim();
  const extensionMatch = source.match(FILE_EXTENSION);
  const extension = extensionMatch?.[1].toUpperCase() ?? null;
  let name = source
    .replace(FILE_EXTENSION, "")
    .replace(STORAGE_PREFIX, "")
    .replace(/([a-z\d])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .replace(/(\S)-(\S)/g, "$1 $2")
    .replace(/\s+/g, " ")
    .trim();

  for (const [pattern, replacement] of VIETNAMESE_DOCUMENT_PHRASES) {
    name = name.replace(pattern, replacement);
  }

  return { name: name || source, extension };
}
