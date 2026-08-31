import type { ReactNode } from "react";

interface AdminPageHeaderProps {
  eyebrow: string;
  title: string;
  description: ReactNode;
  actions?: ReactNode;
}

/** Shared heading for operational Admin pages.
 *
 * Keeping the hierarchy in one component makes every page feel like part of the
 * same dashboard while still letting each workflow supply its own actions.
 */
export function AdminPageHeader({ eyebrow, title, description, actions }: AdminPageHeaderProps) {
  return (
    <header className="admin-page-head business-dashboard-head admin-workspace-head">
      <div>
        <p className="business-eyebrow">{eyebrow}</p>
        <h1 className="page-title">{title}</h1>
        <p className="page-sub">{description}</p>
      </div>
      {actions ? <div className="admin-head-actions business-head-actions">{actions}</div> : null}
    </header>
  );
}
