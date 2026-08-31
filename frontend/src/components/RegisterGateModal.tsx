import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { customerApi } from "../api/customerChat";
import { clearVisitorSession } from "../hooks/useVisitorToken";
import { useAuth } from "../hooks/useAuth";
import type { CustomerChatSessionResponse, CustomerGate, TokenResponse, UserRole } from "../types";
import { PHONE_ERROR, isValidPhone, normalisePhone } from "../utils/phone";
import { EyeIcon, EyeOffIcon, LoaderIcon, XIcon } from "./Icons";

const GATE_COPY: Record<CustomerGate, { title: string; body: string }> = {
  turn_limit: {
    title: "Tiếp tục trò chuyện cùng Auremont",
    body:
      "Cảm ơn bạn đã trò chuyện cùng Auremont! Để mình lưu lại đoạn chat này và tư vấn sâu hơn, " +
      "bạn vui lòng đăng ký/đăng nhập tài khoản nhé.",
  },
  daily_limit: {
    title: "Hết lượt hỏi hôm nay",
    body:
      "Bạn đã dùng hết lượt hỏi miễn phí trong ngày. Đăng ký tài khoản để được hỏi nhiều hơn mỗi ngày " +
      "và lưu lại toàn bộ lịch sử tư vấn nhé!",
  },
  closing_intent: {
    title: "Mở khóa thông tin chi tiết",
    body:
      "Mình đã chuẩn bị sẵn thông tin chi tiết cho bạn. Để bảo mật thông tin dự án, bạn vui lòng " +
      "đăng ký/đăng nhập tài khoản để mình mở khóa tài liệu, hoặc để chuyên viên gọi điện hỗ trợ ngay nhé!",
  },
  human_request: {
    title: "Kết nối chuyên viên tư vấn",
    body:
      "Để kết nối bạn với chuyên viên tư vấn, bạn vui lòng đăng ký/đăng nhập tài khoản nhé — " +
      "mình sẽ báo ngay cho chuyên viên sau khi bạn hoàn tất.",
  },
};

function decodeRoleFromToken(accessToken: string): UserRole {
  const payload = JSON.parse(atob(accessToken.split(".")[1])) as { role: UserRole };
  return payload.role;
}

interface Props {
  gate: CustomerGate;
  /** The in-progress anonymous session to claim on registration, if any. */
  sessionId: number | null;
  visitorToken: string | null;
  onClose: () => void;
  /** Called once login/registration succeeds, so the caller can re-fetch messages
   * under the now-authenticated identity. */
  onAuthenticated: (sessionId?: number) => void;
}

export function RegisterGateModal({ gate, sessionId, visitorToken, onClose, onAuthenticated }: Props) {
  const [mode, setMode] = useState<"register" | "login">("register");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { login } = useAuth();

  const copy = GATE_COPY[gate];
  // The phone is only required when registering — logging in needs email + password only.
  const phoneOk = mode === "login" || isValidPhone(phone);
  const canSubmit = Boolean(email.trim() && password) && phoneOk && !loading;
  const showPhoneError = mode === "register" && phone.trim().length > 0 && !isValidPhone(phone);

  const applySession = (token: TokenResponse, resumedSessionId?: number) => {
    login(token.access_token, token.refresh_token, token.user.role, token.user.username);
    clearVisitorSession();
    onAuthenticated(resumedSessionId);
  };

  const handleRegister = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setError(null);
    setLoading(true);
    try {
      const token = await customerApi.post<TokenResponse>("/customer/register", {
        email: email.trim(),
        password,
        full_name: fullName.trim() || null,
        phone: normalisePhone(phone),
        session_id: sessionId,
        visitor_token: visitorToken,
      });
      applySession(token, sessionId ?? undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Đăng ký thất bại, vui lòng thử lại.");
    } finally {
      setLoading(false);
    }
  };

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setError(null);
    setLoading(true);
    try {
      const body = new URLSearchParams({ username: email.trim(), password });
      const result = await api.postUrlEncoded<{ access_token: string; refresh_token: string }>("/auth/login", body);
      const role = decodeRoleFromToken(result.access_token);
      login(result.access_token, result.refresh_token, role, email.trim());
      let canonicalSessionId: number | undefined;
      if (role === "customer" && sessionId && visitorToken) {
        const canonical = await customerApi.post<CustomerChatSessionResponse>("/customer/sessions/claim-anonymous", {
          session_id: sessionId,
          visitor_token: visitorToken,
        });
        canonicalSessionId = canonical.id;
      }
      clearVisitorSession();
      onAuthenticated(canonicalSessionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Đăng nhập thất bại.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="gate-modal-backdrop" onMouseDown={onClose}>
      <div className="gate-modal" onMouseDown={(e) => e.stopPropagation()}>
        <button className="gate-modal-close" type="button" onClick={onClose} aria-label="Đóng">
          <XIcon size={18} />
        </button>

        <h2 className="gate-modal-title">{copy.title}</h2>
        <p className="gate-modal-desc">{copy.body}</p>

        <div className="gate-modal-tabs">
          <button
            type="button"
            className={`gate-modal-tab ${mode === "register" ? "gate-modal-tab--active" : ""}`}
            onClick={() => setMode("register")}
          >
            Đăng ký
          </button>
          <button
            type="button"
            className={`gate-modal-tab ${mode === "login" ? "gate-modal-tab--active" : ""}`}
            onClick={() => setMode("login")}
          >
            Đã có tài khoản? Đăng nhập
          </button>
        </div>

        <form className="login-form" onSubmit={mode === "register" ? handleRegister : handleLogin} noValidate>
          <div className="login-field">
            <label className="login-label" htmlFor="gate-email">
              Email
            </label>
            <input
              id="gate-email"
              type="email"
              className="login-input"
              placeholder="ban@vidu.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              autoFocus
              disabled={loading}
            />
          </div>

          {mode === "register" && (
            <>
              <div className="login-field">
                <label className="login-label" htmlFor="gate-name">
                  Họ và tên
                </label>
                <input
                  id="gate-name"
                  type="text"
                  className="login-input"
                  placeholder="Nguyễn Văn A"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  autoComplete="name"
                  disabled={loading}
                />
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="gate-phone">
                  Số điện thoại
                </label>
                <input
                  id="gate-phone"
                  type="tel"
                  inputMode="tel"
                  className="login-input"
                  placeholder="0912345678"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  autoComplete="tel"
                  disabled={loading}
                />
                {showPhoneError && <span className="login-field-error">{PHONE_ERROR}</span>}
              </div>
            </>
          )}

          <div className="login-field">
            <label className="login-label" htmlFor="gate-password">
              Mật khẩu
            </label>
            <div className="login-input-wrap">
              <input
                id="gate-password"
                type={showPwd ? "text" : "password"}
                className="login-input login-input--pwd"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                minLength={mode === "register" ? 8 : undefined}
                disabled={loading}
              />
              <button
                type="button"
                className="login-eye"
                onClick={() => setShowPwd((v) => !v)}
                tabIndex={-1}
                aria-label={showPwd ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
              >
                {showPwd ? <EyeOffIcon size={16} /> : <EyeIcon size={16} />}
              </button>
            </div>
            {mode === "register" && <span className="field-hint">Tối thiểu 8 ký tự.</span>}
          </div>

          {error && <div className="login-error">{error}</div>}

          <button type="submit" className="btn btn-primary login-submit" disabled={!canSubmit}>
            {loading ? (
              <>
                <LoaderIcon size={16} className="icon-spin" />
                Đang xử lý...
              </>
            ) : mode === "register" ? (
              "Đăng ký & tiếp tục trò chuyện"
            ) : (
              "Đăng nhập"
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
