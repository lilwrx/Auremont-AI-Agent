import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import { useAuth } from "../../hooks/useAuth";
import type { UserRole } from "../../types";
import { ArrowLeftIcon, EyeIcon, EyeOffIcon, LoaderIcon, LogInIcon, AuremontLogoIcon } from "../../components/Icons";

const HERO_IMAGE_URL =
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/vinhomes-ocean-park/masteri-grand-coast-bg-homepage.jpg";

interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

function decodeRoleFromToken(accessToken: string): UserRole {
  // backend/core/security.py create_access_token embeds {"role":...} in the JWT payload.
  const payload = JSON.parse(atob(accessToken.split(".")[1])) as { role: UserRole };
  return payload.role;
}

// Shared internal login screen; routes to SALE or ADMIN flow after authentication.
export function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const canSubmit = Boolean(username.trim() && password) && !loading;

  // POST /auth/login uses OAuth2PasswordRequestForm, so the body must be
  // form-urlencoded, not JSON.
  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setError(null);
    setLoading(true);
    try {
      const body = new URLSearchParams({ username: username.trim(), password });
      const result = await api.postUrlEncoded<TokenResponse>("/auth/login", body);
      const role = decodeRoleFromToken(result.access_token);
      login(result.access_token, result.refresh_token, role, username.trim());
      navigate("/home", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Đăng nhập thất bại");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page" style={{ "--hero-image-url": `url(${HERO_IMAGE_URL})` } as React.CSSProperties}>
      <div className="login-page-scrim" />

      <Link to="/" className="login-home-link">
        <ArrowLeftIcon size={16} />
        <span>Trang chủ</span>
      </Link>

      <div className="login-card">
        <div className="login-logo">
          <AuremontLogoIcon size={36} />
          <span className="logo-text" style={{ fontSize: "1.25rem" }}>Auremont</span>
        </div>

        <h1 className="login-title">Đăng nhập</h1>
        <p className="login-subtitle">Dùng tài khoản nội bộ Sale hoặc Admin để tiếp tục.</p>

        <form className="login-form" onSubmit={handleSubmit} noValidate>
          <div className="login-field">
            <label className="login-label" htmlFor="username">
              Tên đăng nhập
            </label>
            <input
              id="username"
              type="text"
              className="login-input"
              placeholder="admin"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              disabled={loading}
            />
          </div>

          <div className="login-field">
            <label className="login-label" htmlFor="password">
              Mật khẩu
            </label>
            <div className="login-input-wrap">
              <input
                id="password"
                type={showPwd ? "text" : "password"}
                className="login-input login-input--pwd"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
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
          </div>

          {error && <div className="login-error">{error}</div>}

          <button type="submit" className="btn btn-primary login-submit" disabled={!canSubmit}>
            {loading ? (
              <>
                <LoaderIcon size={16} className="icon-spin" />
                Đang đăng nhập...
              </>
            ) : (
              <>
                Đăng nhập
                <LogInIcon size={15} />
              </>
            )}
          </button>
        </form>

        <p className="login-hint">Hệ thống tự chuyển tới màn hình phù hợp theo vai trò tài khoản.</p>
        <p className="login-hint">
          Là khách hàng, chưa có tài khoản? <Link to="/register">Đăng ký ngay</Link>
        </p>
      </div>
    </div>
  );
}
