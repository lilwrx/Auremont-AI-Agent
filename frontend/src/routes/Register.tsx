import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { customerApi } from "../api/customerChat";
import { getVisitorSession, clearVisitorSession } from "../hooks/useVisitorToken";
import { useAuth } from "../hooks/useAuth";
import type { TokenResponse } from "../types";
import { PHONE_ERROR, isValidPhone, normalisePhone } from "../utils/phone";
import { EyeIcon, EyeOffIcon, LoaderIcon, LogInIcon, AuremontLogoIcon } from "../components/Icons";

const HERO_IMAGE_URL =
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/vinhomes-ocean-park/masteri-grand-coast-bg-homepage.jpg";

// Standalone customer registration screen — a full page, not just the mid-chat gate
// modal (RegisterGateModal.tsx), so a visitor can create an account straight from the
// login screen instead of only after being prompted a few messages into a chat. Same
// POST /customer/register endpoint either way; if the visitor was already chatting
// anonymously, their in-progress session is claimed here too, exactly like the modal does.
export function Register() {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const showPhoneError = phone.trim().length > 0 && !isValidPhone(phone);
  const canSubmit = Boolean(email.trim() && password) && isValidPhone(phone) && !loading;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setError(null);
    setLoading(true);
    try {
      const visitor = getVisitorSession();
      const token = await customerApi.post<TokenResponse>("/customer/register", {
        email: email.trim(),
        password,
        full_name: fullName.trim() || null,
        phone: normalisePhone(phone),
        session_id: visitor?.sessionId ?? null,
        visitor_token: visitor?.visitorToken ?? null,
      });
      login(token.access_token, token.refresh_token, token.user.role, token.user.username);
      clearVisitorSession();
      navigate("/home", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Đăng ký thất bại, vui lòng thử lại.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page" style={{ "--hero-image-url": `url(${HERO_IMAGE_URL})` } as React.CSSProperties}>
      <div className="login-page-scrim" />

      <div className="login-card">
        <div className="login-logo">
          <AuremontLogoIcon size={36} />
          <span className="logo-text" style={{ fontSize: "1.25rem" }}>
            Auremont
          </span>
        </div>

        <h1 className="login-title">Đăng ký tài khoản</h1>
        <p className="login-subtitle">Tạo tài khoản khách hàng để lưu lại lịch sử trò chuyện và nhận tư vấn sâu hơn.</p>

        <form className="login-form" onSubmit={handleSubmit} noValidate>
          <div className="login-field">
            <label className="login-label" htmlFor="register-email">
              Email
            </label>
            <input
              id="register-email"
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

          <div className="login-field">
            <label className="login-label" htmlFor="register-name">
              Họ và tên
            </label>
            <input
              id="register-name"
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
            <label className="login-label" htmlFor="register-phone">
              Số điện thoại
            </label>
            <input
              id="register-phone"
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

          <div className="login-field">
            <label className="login-label" htmlFor="register-password">
              Mật khẩu
            </label>
            <div className="login-input-wrap">
              <input
                id="register-password"
                type={showPwd ? "text" : "password"}
                className="login-input login-input--pwd"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                minLength={8}
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
            <span className="field-hint">Tối thiểu 8 ký tự.</span>
          </div>

          {error && <div className="login-error">{error}</div>}

          <button type="submit" className="btn btn-primary login-submit" disabled={!canSubmit}>
            {loading ? (
              <>
                <LoaderIcon size={16} className="icon-spin" />
                Đang đăng ký...
              </>
            ) : (
              <>
                Đăng ký
                <LogInIcon size={15} />
              </>
            )}
          </button>
        </form>

        <p className="login-hint">
          Đã có tài khoản? <Link to="/login">Đăng nhập</Link>
        </p>
      </div>
    </div>
  );
}
