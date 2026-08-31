import type { ReactNode } from "react";

interface AdminMetricCardProps {
  label: string;
  value: string | number;
  hint: string;
  icon: ReactNode;
  tone?: "default" | "success" | "warning" | "caution" | "danger";
  tooltip?: string;
  active?: boolean;
  onClick?: () => void;
}

export function AdminMetricCard({
  label,
  value,
  hint,
  icon,
  tone = "default",
  tooltip,
  active = false,
  onClick,
}: AdminMetricCardProps) {
  const className = `admin-metric admin-metric--${tone}${onClick ? " admin-metric--interactive" : ""}${active ? " is-active" : ""}`;
  const content = (
    <>
      <div className="admin-metric-icon">{icon}</div>
      <div>
        <span className="admin-metric-label">{label}</span>
        <strong className="admin-metric-value">{value}</strong>
        <span className="admin-metric-hint">{hint}</span>
      </div>
      {tooltip ? <span className="admin-metric-tooltip" role="tooltip">{tooltip}</span> : null}
    </>
  );

  if (onClick) {
    return <button type="button" className={className} onClick={onClick} aria-pressed={active}>{content}</button>;
  }

  return <article className={className}>{content}</article>;
}
