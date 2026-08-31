import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { billingApi, formatVnd, type Plan, type PlanId, type Quote } from "../api/billing";
import { AuremontLogoIcon, CheckCircleIcon, LoaderIcon } from "../components/Icons";
import { PHONE_ERROR, isValidPhone, normalisePhone } from "../utils/phone";

const HERO_IMAGE_URL =
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/vinhomes-ocean-park/masteri-grand-coast-bg-homepage.jpg";

// Business sign-up, deliberately separate from /register.
//
// /register creates a CUSTOMER account for someone who wants to chat about a property.
// This creates nothing at all: it files a subscription request that an Admin approves,
// and approval is what provisions the workspace, the owner account and the subscription
// together. Sharing one route would mean one form that sometimes makes an account and
// sometimes does not, with two different meanings for the same password field.
type Step = "plan" | "details" | "review" | "done";

export function RegisterBusiness() {
  const [searchParams] = useSearchParams();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [plansError, setPlansError] = useState<string | null>(null);
  const [planId, setPlanId] = useState<PlanId | null>(null);
  const [seats, setSeats] = useState<number>(0);
  const [step, setStep] = useState<Step>("plan");

  const [companyName, setCompanyName] = useState("");
  const [contactName, setContactName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [taxCode, setTaxCode] = useState("");
  const [billingAddress, setBillingAddress] = useState("");
  const [note, setNote] = useState("");

  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    billingApi
      .listPlans()
      .then((rows) => {
        setPlans(rows);
        // ?plan=growth arrives from the pricing page's Đăng ký button; seats default to
        // the plan minimum so the first quote the applicant sees is a valid one.
        const requested = searchParams.get("plan") as PlanId | null;
        const chosen = rows.find((row) => row.id === requested) ?? null;
        if (chosen) {
          setPlanId(chosen.id);
          setSeats(chosen.min_seats);
          setStep("details");
        }
      })
      .catch(() => setPlansError("Không tải được bảng giá. Vui lòng thử lại sau."));
  }, [searchParams]);

  const selectedPlan = useMemo(() => plans.find((plan) => plan.id === planId) ?? null, [plans, planId]);
  const showPhoneError = phone.trim().length > 0 && !isValidPhone(phone);

  const canSubmitDetails =
    Boolean(companyName.trim() && contactName.trim() && email.trim() && password.length >= 8) &&
    isValidPhone(phone) &&
    selectedPlan !== null &&
    seats >= selectedPlan.min_seats;

  const choosePlan = (plan: Plan) => {
    setPlanId(plan.id);
    setSeats(plan.min_seats);
    setStep("details");
  };

  const goToReview = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmitDetails || planId === null) return;
    setError(null);
    try {
      // Priced by the backend: a subtotal computed in the browser could drift from the
      // seeded price without anyone noticing.
      setQuote(await billingApi.quote(planId, seats));
      setStep("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tính được chi phí. Vui lòng thử lại.");
    }
  };

  const submit = async () => {
    if (planId === null) return;
    setError(null);
    setSubmitting(true);
    try {
      await billingApi.submitRequest({
        plan_id: planId,
        seats,
        company_name: companyName.trim(),
        contact_name: contactName.trim(),
        contact_email: email.trim(),
        contact_phone: normalisePhone(phone),
        password,
        tax_code: taxCode.trim() || null,
        billing_address: billingAddress.trim() || null,
        note: note.trim() || null,
      });
      setStep("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gửi yêu cầu thất bại, vui lòng thử lại.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page" style={{ "--hero-image-url": `url(${HERO_IMAGE_URL})` } as React.CSSProperties}>
      <div className="login-page-scrim" />

      <div className="login-card register-business-card">
        <div className="login-logo">
          <AuremontLogoIcon size={36} />
          <span className="logo-text" style={{ fontSize: "1.25rem" }}>
            Auremont
          </span>
        </div>

        {step === "done" ? (
          <div className="register-business-done">
            <CheckCircleIcon size={44} />
            <h1 className="login-title">Đã nhận yêu cầu đăng ký</h1>
            <p className="login-subtitle">
              Bộ phận kinh doanh sẽ liên hệ với <strong>{email.trim()}</strong> trong vòng 1 ngày làm việc để xác nhận
              thanh toán và kích hoạt workspace. Tài khoản của bạn sẽ dùng chính email và mật khẩu vừa đăng ký.
            </p>
            <Link to="/" className="btn btn-outline register-business-back">
              Về trang chủ
            </Link>
          </div>
        ) : (
          <>
            <h1 className="login-title">Đăng ký gói doanh nghiệp</h1>
            <p className="login-subtitle">
              Dành cho sàn giao dịch và đội ngũ Sale. Tài khoản khách hàng cá nhân vui lòng dùng{" "}
              <Link to="/register">đăng ký thường</Link>.
            </p>

            <ol className="register-business-steps" aria-label="Các bước đăng ký">
              <li className={step === "plan" ? "is-active" : "is-done"}>Chọn gói</li>
              <li className={step === "details" ? "is-active" : step === "review" ? "is-done" : ""}>
                Thông tin doanh nghiệp
              </li>
              <li className={step === "review" ? "is-active" : ""}>Xác nhận chi phí</li>
            </ol>

            {plansError ? <div className="alert alert-danger">{plansError}</div> : null}
            {error ? <div className="alert alert-danger">{error}</div> : null}

            {step === "plan" ? (
              <div className="register-business-plans">
                {plans.map((plan) => (
                  <button
                    type="button"
                    key={plan.id}
                    className="register-business-plan"
                    onClick={() => choosePlan(plan)}
                  >
                    <strong>{plan.name}</strong>
                    <span className="register-business-plan-price">
                      {formatVnd(plan.price_per_seat_vnd)} / seat / tháng
                    </span>
                    <span className="register-business-plan-note">Tối thiểu {plan.min_seats} seat</span>
                    <span className="register-business-plan-note">
                      {plan.conversations_per_seat === null
                        ? "Không giới hạn cứng số cuộc tư vấn"
                        : `${plan.conversations_per_seat.toLocaleString("vi-VN")} cuộc tư vấn / seat / tháng`}
                    </span>
                  </button>
                ))}
              </div>
            ) : null}

            {step === "details" && selectedPlan ? (
              <form className="login-form" onSubmit={goToReview}>
                <div className="register-business-chosen">
                  <span>
                    Gói <strong>{selectedPlan.name}</strong> — {formatVnd(selectedPlan.price_per_seat_vnd)}/seat/tháng
                  </span>
                  <button type="button" className="link-button" onClick={() => setStep("plan")}>
                    Đổi gói
                  </button>
                </div>

                <label className="login-label">
                  Số seat (số Sale sử dụng)
                  <input
                    className="login-input"
                    type="number"
                    min={selectedPlan.min_seats}
                    max={1000}
                    value={seats}
                    onChange={(event) => setSeats(Number(event.target.value))}
                    required
                  />
                </label>
                {seats < selectedPlan.min_seats ? (
                  <span className="login-field-error">Gói {selectedPlan.name} yêu cầu tối thiểu {selectedPlan.min_seats} seat.</span>
                ) : null}

                <label className="login-label">
                  Tên doanh nghiệp
                  <input
                    className="login-input"
                    value={companyName}
                    onChange={(event) => setCompanyName(event.target.value)}
                    required
                  />
                </label>

                <label className="login-label">
                  Họ tên người đại diện
                  <input
                    className="login-input"
                    value={contactName}
                    onChange={(event) => setContactName(event.target.value)}
                    required
                  />
                </label>

                <label className="login-label">
                  Email công việc
                  <input
                    className="login-input"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                  />
                </label>

                <label className="login-label">
                  Số điện thoại
                  <input
                    className="login-input"
                    value={phone}
                    onChange={(event) => setPhone(event.target.value)}
                    required
                  />
                </label>
                {showPhoneError ? <span className="login-field-error">{PHONE_ERROR}</span> : null}

                <label className="login-label">
                  Mật khẩu (tối thiểu 8 ký tự)
                  <input
                    className="login-input"
                    type="password"
                    minLength={8}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                  />
                </label>

                <label className="login-label">
                  Mã số thuế (không bắt buộc)
                  <input className="login-input" value={taxCode} onChange={(e) => setTaxCode(e.target.value)} />
                </label>

                <label className="login-label">
                  Địa chỉ xuất hoá đơn (không bắt buộc)
                  <input
                    className="login-input"
                    value={billingAddress}
                    onChange={(event) => setBillingAddress(event.target.value)}
                  />
                </label>

                <label className="login-label">
                  Ghi chú (không bắt buộc)
                  <textarea
                    className="login-input"
                    rows={3}
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                  />
                </label>

                <button className="btn btn-primary login-submit" type="submit" disabled={!canSubmitDetails}>
                  Xem lại chi phí
                </button>
              </form>
            ) : null}

            {step === "review" && quote ? (
              <div className="register-business-review">
                <dl>
                  <div>
                    <dt>Gói</dt>
                    <dd>{quote.plan_name}</dd>
                  </div>
                  <div>
                    <dt>Số seat</dt>
                    <dd>{quote.seats}</dd>
                  </div>
                  <div>
                    <dt>Đơn giá</dt>
                    <dd>{formatVnd(quote.price_per_seat_vnd)} / seat / tháng</dd>
                  </div>
                  <div>
                    <dt>Hạn mức tư vấn AI</dt>
                    <dd>
                      {quote.included_conversations === null
                        ? "Không giới hạn cứng"
                        : `${quote.included_conversations.toLocaleString("vi-VN")} cuộc / tháng`}
                    </dd>
                  </div>
                  <div>
                    <dt>Phí vượt hạn mức</dt>
                    <dd>{formatVnd(quote.overage_price_vnd)} / cuộc</dd>
                  </div>
                  <div className="register-business-total">
                    <dt>Tổng mỗi tháng</dt>
                    <dd>{formatVnd(quote.monthly_total_vnd)}</dd>
                  </div>
                </dl>

                <p className="register-business-hint">
                  Gửi yêu cầu chưa phát sinh thanh toán. Bộ phận kinh doanh sẽ liên hệ xác nhận trước khi kích hoạt.
                </p>

                <div className="register-business-actions">
                  <button type="button" className="btn btn-outline" onClick={() => setStep("details")}>
                    Quay lại
                  </button>
                  <button type="button" className="btn btn-primary" onClick={submit} disabled={submitting}>
                    {submitting ? <LoaderIcon size={16} className="is-spinning" /> : null}
                    Gửi yêu cầu đăng ký
                  </button>
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
