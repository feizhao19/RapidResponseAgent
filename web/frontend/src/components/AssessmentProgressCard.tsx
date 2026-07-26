import type { AssessmentProgressView } from "../assessmentJobMessage";

type Props = {
  view: AssessmentProgressView;
};

function titleFor(status: string): string {
  if (status === "completed") return "Assessment complete";
  if (status === "failed") return "Assessment failed";
  if (status === "cancelled") return "Assessment cancelled";
  return "Running assessment";
}

export function AssessmentProgressCard({ view }: Props) {
  const percent = Math.max(0, Math.min(100, view.percent));
  const live = view.status === "running" || view.status === "queued" || view.status === "aligning";

  return (
    <div
      className={`assessment-progress-card status-${view.status}${live ? " is-live" : ""}`}
      role="status"
      aria-live="polite"
    >
      <div className="assessment-progress-header">
        <span className="assessment-progress-title">{titleFor(view.status)}</span>
        <span className="assessment-progress-pct">{percent}%</span>
      </div>
      <div
        className="assessment-progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label="Assessment progress"
      >
        <div className="assessment-progress-fill" style={{ width: `${percent}%` }} />
      </div>
      {view.step && (
        <div className="assessment-progress-step" title={view.step}>
          {view.step}
        </div>
      )}
      {view.detail && (
        <div className="assessment-progress-detail" title={view.detail}>
          {view.detail}
        </div>
      )}
    </div>
  );
}
