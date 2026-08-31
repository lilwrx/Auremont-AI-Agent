import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { EyeIcon, EyeOffIcon, UserIcon, XIcon } from "../Icons";
import { adminDashboardApi } from "../../api/adminDashboard";
import type { SaleStatus } from "../../types/admin";

interface CreateSaleAccountModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (sale: SaleStatus) => void;
}

interface SaleAccountForm {
  username: string;
  email: string;
  password: string;
  confirmPassword: string;
  isActive: boolean;
}

const EMPTY_FORM: SaleAccountForm = {
  username: "",
  email: "",
  password: "",
  confirmPassword: "",
  isActive: true,
};

const USERNAME_PATTERN = /^[A-Za-z0-9._-]+$/;

export function CreateSaleAccountModal({ isOpen, onClose, onCreated }: CreateSaleAccountModalProps) {
  const [form, setForm] = useState<SaleAccountForm>(EMPTY_FORM);
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();
  const usernameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    usernameRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submitting) onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose, submitting]);

  if (!isOpen) return null;

  const updateField = <Key extends keyof SaleAccountForm>(key: Key, value: SaleAccountForm[Key]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    const username = form.username.trim();
    if (!USERNAME_PATTERN.test(username)) {
      setError("Tên đăng nhập chỉ được gồm chữ cái, chữ số, dấu chấm, gạch dưới hoặc gạch ngang.");
      return;
    }
    if (form.password.length < 8 || !/[A-Za-z]/.test(form.password) || !/\d/.test(form.password)) {
      setError("Mật khẩu phải có ít nhất 8 ký tự, gồm tối thiểu một chữ cái và một chữ số.");
      return;
    }
    if (new TextEncoder().encode(form.password).length > 72) {
      setError("Mật khẩu không được vượt quá 72 byte.");
      return;
    }
    if (form.password !== form.confirmPassword) {
      setError("Mật khẩu xác nhận chưa khớp.");
      return;
    }

    setSubmitting(true);
    try {
      const sale = await adminDashboardApi.createSale({
        username,
        email: form.email.trim().toLowerCase(),
        password: form.password,
        is_active: form.isActive,
      });
      setForm(EMPTY_FORM);
      setShowPassword(false);
      onCreated(sale);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không tạo được tài khoản Sale.");
    } finally {
      setSubmitting(false);
    }
  };

  const close = () => {
    if (submitting) return;
    setError(null);
    setForm(EMPTY_FORM);
    setShowPassword(false);
    onClose();
  };

  return (
    <div
      className="admin-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <section className="sale-account-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header className="sale-account-dialog-head">
          <div className="sale-account-dialog-title">
            <span><UserIcon size={20} /></span>
            <div>
              <small>Sales account</small>
              <h2 id={titleId}>Tạo tài khoản Sale</h2>
            </div>
          </div>
          <button type="button" className="sale-account-close" onClick={close} disabled={submitting} aria-label="Đóng">
            <XIcon size={18} />
          </button>
        </header>

        <form className="sale-account-form" onSubmit={(event) => void submit(event)}>
          <p className="sale-account-intro">
            Tài khoản được gán cố định vai trò Sale. Mật khẩu chỉ dùng để tạo thông tin đăng nhập và không được hiển thị lại.
          </p>

          {error ? <div className="alert alert-danger" role="alert">{error}</div> : null}

          <div className="sale-account-form-grid">
            <label className="field">
              Tên đăng nhập
              <input
                ref={usernameRef}
                type="text"
                value={form.username}
                onChange={(event) => updateField("username", event.target.value)}
                autoComplete="username"
                minLength={3}
                maxLength={50}
                pattern="[A-Za-z0-9._-]+"
                placeholder="Ví dụ: sale.ha"
                required
              />
              <span className="field-hint">3–50 ký tự; cho phép . _ và -</span>
            </label>

            <label className="field">
              Email
              <input
                type="email"
                value={form.email}
                onChange={(event) => updateField("email", event.target.value)}
                autoComplete="email"
                maxLength={100}
                placeholder="sale.ha@company.vn"
                required
              />
              <span className="field-hint">Dùng để nhận diện và liên hệ nội bộ.</span>
            </label>

            <label className="field">
              Mật khẩu tạm thời
              <span className="sale-account-password">
                <input
                  type={showPassword ? "text" : "password"}
                  value={form.password}
                  onChange={(event) => updateField("password", event.target.value)}
                  autoComplete="new-password"
                  minLength={8}
                  maxLength={72}
                  placeholder="Tối thiểu 8 ký tự"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((visible) => !visible)}
                  aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
                  aria-pressed={showPassword}
                >
                  {showPassword ? <EyeOffIcon size={17} /> : <EyeIcon size={17} />}
                </button>
              </span>
              <span className="field-hint">Ít nhất một chữ cái và một chữ số.</span>
            </label>

            <label className="field">
              Xác nhận mật khẩu
              <input
                type={showPassword ? "text" : "password"}
                value={form.confirmPassword}
                onChange={(event) => updateField("confirmPassword", event.target.value)}
                autoComplete="new-password"
                minLength={8}
                maxLength={72}
                placeholder="Nhập lại mật khẩu"
                required
              />
              <span className="field-hint">Phải trùng với mật khẩu tạm thời.</span>
            </label>
          </div>

          <label className="sale-account-active-option">
            <input
              type="checkbox"
              checked={form.isActive}
              onChange={(event) => updateField("isActive", event.target.checked)}
            />
            <span>
              <strong>Kích hoạt tài khoản ngay</strong>
              <small>Sale có thể đăng nhập ngay sau khi Admin tạo thành công.</small>
            </span>
          </label>

          <footer className="sale-account-dialog-actions">
            <button type="button" className="btn btn-outline" onClick={close} disabled={submitting}>Hủy</button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? "Đang tạo…" : "Tạo tài khoản"}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}
