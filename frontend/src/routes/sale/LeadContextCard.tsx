import type { LeadDetail } from "../../types";
import { BuildingHomeIcon, TargetIcon, UsersIcon } from "../../components/Icons";

/** A short brief pinned above the transcript: what the AI already learned before handing
 * the customer over. Without it the Sale opens a claimed session and has to read the whole
 * history to find out what the person actually wants — which is the one thing the handoff
 * message promises they will not have to ask again. */
export function LeadContextCard({ lead }: { lead: LeadDetail | null }) {
  if (!lead) return null;

  const facts: { icon: React.ReactNode; label: string; value: string }[] = [];
  if (lead.budgets.length > 0) {
    facts.push({ icon: <TargetIcon size={14} />, label: "Ngân sách", value: lead.budgets.join(" · ") });
  }
  if (lead.unit_types.length > 0) {
    facts.push({ icon: <BuildingHomeIcon size={14} />, label: "Loại căn", value: lead.unit_types.join(" · ") });
  }
  if (lead.projects.length > 0) {
    facts.push({ icon: <BuildingHomeIcon size={14} />, label: "Quan tâm", value: lead.projects.join(" · ") });
  }

  // Nothing learned yet and nothing the model volunteered — a card saying "we know nothing"
  // is worse than no card, so render neither.
  if (facts.length === 0 && !lead.llm_reason) return null;

  return (
    <div className="lead-context-card">
      <div className="lead-context-head">
        <UsersIcon size={14} />
        <span>AI đã tìm hiểu được</span>
      </div>

      {facts.length > 0 && (
        <div className="lead-context-facts">
          {facts.map((fact) => (
            <div className="lead-context-fact" key={fact.label}>
              {fact.icon}
              <span className="lead-context-fact-label">{fact.label}</span>
              <strong>{fact.value}</strong>
            </div>
          ))}
        </div>
      )}

      {lead.llm_reason && <p className="lead-context-note">{lead.llm_reason}</p>}
    </div>
  );
}
