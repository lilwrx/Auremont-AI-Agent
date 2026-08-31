import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { billingApi, formatVnd, type Plan } from "../api/billing";
import { ArrowRightIcon, CheckCircleIcon } from "./Icons";

// Priced per seat (the number of Sales using the AI), like most B2B CRMs — easier to
// compare than a whole-company conversation count, which nobody can estimate before they
// have used the product. Every plan carries the full feature set; only the seat minimum,
// the pooled quota and the support level differ.
//
// The rows come from GET /billing/plans so the marketing page and the biller can never
// quote different numbers. FALLBACK_PLANS exists only for the window where that request
// fails: a pricing section that renders nothing is worse than one that renders the prices
// we shipped with, and the Đăng ký flow re-reads the live plan anyway.
const FALLBACK_PLANS: Plan[] = [
  {
    id: "starter",
    name: "Starter",
    description: null,
    price_per_seat_vnd: 390_000,
    min_seats: 1,
    conversations_per_seat: 150,
    overage_price_vnd: 2_000,
    support_note: "Hỗ trợ qua email, phản hồi trong 24h",
    sort_order: 1,
  },
  {
    id: "growth",
    name: "Growth",
    description: null,
    price_per_seat_vnd: 550_000,
    min_seats: 3,
    conversations_per_seat: 400,
    overage_price_vnd: 2_000,
    support_note: "Hỗ trợ ưu tiên trong giờ hành chính",
    sort_order: 2,
  },
  {
    id: "enterprise",
    name: "Enterprise",
    description: null,
    price_per_seat_vnd: 420_000,
    min_seats: 20,
    conversations_per_seat: null,
    overage_price_vnd: 2_000,
    support_note: "SLA riêng, hỗ trợ kỹ thuật 24/7",
    sort_order: 3,
  },
];

const CTA_LABEL = "Đăng ký";
const FEATURED_PLAN_ID = "growth";

const SHARED_FEATURES = [
  "AI tư vấn khách hàng 24/7",
  "Phân loại lead COLD / WARM / HOT",
  "Sales tiếp quản và theo dõi hội thoại",
  "Phân quyền theo team / dự án",
  "Dashboard, báo cáo hiệu suất đầy đủ",
  "Tích hợp CRM / Zalo OA",
] as const;

function seatsNote(plan: Plan): string {
  // Enterprise's lower per-seat price is a volume discount, so the minimum is part of the
  // price rather than a footnote — "Từ ... — tối thiểu 20 seat" says that in one line.
  return plan.min_seats > 1 ? `Từ ${plan.min_seats} seat trở lên` : "Tối thiểu 1 seat";
}

function quotaLabel(plan: Plan): string {
  return plan.conversations_per_seat === null
    ? "Không giới hạn cứng"
    : plan.conversations_per_seat.toLocaleString("vi-VN");
}

export function PricingSection() {
  const [plans, setPlans] = useState<Plan[]>(FALLBACK_PLANS);

  useEffect(() => {
    billingApi
      .listPlans()
      .then((rows) => {
        if (rows.length > 0) setPlans(rows);
      })
      .catch(() => {
        /* Keep the shipped prices on screen; the sign-up flow reads the live plan itself. */
      });
  }, []);

  const overageNote = `Vượt hạn mức: ${formatVnd(plans[0]?.overage_price_vnd ?? 2000)}/cuộc, không tạm ngưng AI giữa tháng.`;

  return (
    <section className="business-pricing" id="bang-gia" aria-labelledby="business-pricing-title">
      <div className="container">
        <header className="business-pricing-head">
          <p className="section-eyebrow">Bảng giá dành cho doanh nghiệp</p>
          <h2 className="business-pricing-title" id="business-pricing-title">
            Trả theo số Sale đang dùng
          </h2>
          <p className="business-pricing-subtitle">
            Mọi gói đều có toàn bộ tính năng AI. Không tính theo tổng hội thoại toàn công ty —
            chi phí tăng đúng theo quy mô đội ngũ thực tế, chỉ khác nhau về hạn mức và mức hỗ trợ.
          </p>
        </header>

        <div className="business-pricing-grid">
          {plans.map((plan) => {
            const featured = plan.id === FEATURED_PLAN_ID;
            return (
              <article
                key={plan.id}
                className={`business-pricing-plan${featured ? " business-pricing-plan--featured" : ""}`}
              >
                {featured && <span className="business-pricing-badge">Phổ biến nhất</span>}

                <h3 className="business-pricing-plan-name">{plan.name}</h3>
                <div
                  className="business-pricing-price"
                  aria-label={`${plan.price_per_seat_vnd} đồng mỗi seat mỗi tháng`}
                >
                  <strong>{plan.price_per_seat_vnd.toLocaleString("vi-VN")}</strong>
                  <small>đ</small>
                </div>
                <p className="business-pricing-unit">seat / tháng</p>
                <p className="business-pricing-seats-note">{seatsNote(plan)}</p>

                <p className="business-pricing-quota">
                  <strong>{quotaLabel(plan)}</strong> cuộc tư vấn AI / seat / tháng
                </p>
                <p className="business-pricing-quota-note">
                  Hạn mức gộp chung cho cả team, không chia cứng theo người
                </p>

                <div className="business-pricing-included">
                  <CheckCircleIcon size={19} />
                  <span>Đầy đủ mọi tính năng</span>
                </div>
                <p className="business-pricing-support-note">{plan.support_note}</p>

                <Link
                  to={`/register-business?plan=${plan.id}`}
                  className={`btn business-pricing-cta ${featured ? "btn-primary" : "btn-outline"}`}
                  aria-label={`${CTA_LABEL} gói ${plan.name}`}
                >
                  {CTA_LABEL}
                  <ArrowRightIcon size={16} />
                </Link>
              </article>
            );
          })}
        </div>

        <div className="business-pricing-benefits" aria-label="Quyền lợi chung của mọi gói">
          {SHARED_FEATURES.map((feature) => (
            <div key={feature} className="business-pricing-benefit">
              <CheckCircleIcon size={18} />
              <span>{feature}</span>
            </div>
          ))}
        </div>

        <p className="business-pricing-footnote">
          {overageNote} Hạn mức được làm mới mỗi tháng. Có thể nâng/hạ số seat bất cứ lúc nào.
        </p>
      </div>
    </section>
  );
}
