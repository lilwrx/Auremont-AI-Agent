import { useState } from "react";
import { apiFetch, ApiError } from "../../api/client";
import { PlayIcon } from "../Icons";

const PRESETS = [
  { label: "System metrics", method: "GET", path: "/admin/observability?days=14", body: "" },
  { label: "RAG / Chat", method: "POST", path: "/sale/sessions/1/messages", body: '{\n  "content": "Chính sách giá mới nhất là gì?"\n}' },
  { label: "Lead routing", method: "POST", path: "/admin/sales/reassign", body: '{\n  "session_id": 1,\n  "to_sale_id": 1\n}' },
] as const;

export function ApiTester() {
  const [method, setMethod] = useState("GET");
  const [path, setPath] = useState<string>(PRESETS[0].path);
  const [body, setBody] = useState("");
  const [result, setResult] = useState<string>("");
  const [duration, setDuration] = useState<number | null>(null);
  const [running, setRunning] = useState(false);

  const choosePreset = (value: string) => {
    const preset = PRESETS[Number(value)];
    setMethod(preset.method);
    setPath(preset.path);
    setBody(preset.body);
    setResult("");
  };

  const execute = async () => {
    setRunning(true);
    setResult("");
    const started = performance.now();
    try {
      if (!path.startsWith("/")) throw new Error("Endpoint phải bắt đầu bằng dấu /.");
      let parsedBody: unknown;
      if (method !== "GET" && method !== "DELETE" && body.trim()) parsedBody = JSON.parse(body);
      const response = await apiFetch<unknown>(path, {
        method,
        body: parsedBody === undefined ? undefined : JSON.stringify(parsedBody),
      });
      setResult(JSON.stringify(response, null, 2));
    } catch (error) {
      const status = error instanceof ApiError ? `HTTP ${error.status}\n` : "";
      setResult(`${status}${error instanceof Error ? error.message : "Request failed"}`);
    } finally {
      setDuration(Math.round(performance.now() - started));
      setRunning(false);
    }
  };

  return (
    <div className="api-tester">
      <div className="api-tester-presets">
        <label htmlFor="api-preset">Kịch bản nhanh</label>
        <select id="api-preset" defaultValue="0" onChange={(event) => choosePreset(event.target.value)}>
          {PRESETS.map((preset, index) => <option key={preset.label} value={index}>{preset.label}</option>)}
        </select>
      </div>
      <div className="api-request-line">
        <select aria-label="HTTP method" value={method} onChange={(event) => setMethod(event.target.value)}>
          {['GET', 'POST', 'PATCH', 'PUT', 'DELETE'].map((value) => <option key={value}>{value}</option>)}
        </select>
        <input value={path} onChange={(event) => setPath(event.target.value)} aria-label="API endpoint" />
        <button type="button" className="btn btn-primary" onClick={execute} disabled={running}>
          <PlayIcon size={14} /> {running ? "Đang chạy" : "Gửi"}
        </button>
      </div>
      {method !== "GET" && method !== "DELETE" && (
        <textarea value={body} onChange={(event) => setBody(event.target.value)} spellCheck={false} aria-label="JSON request body" />
      )}
      <div className="api-response-head"><span>Response</span>{duration != null && <span>{duration} ms</span>}</div>
      <pre className="api-response">{result || "Kết quả JSON sẽ hiển thị tại đây."}</pre>
      <p className="admin-footnote">Tester dùng quyền Admin hiện tại. Preset Chat cần thay ID bằng một session thuộc tài khoản đang đăng nhập.</p>
    </div>
  );
}
