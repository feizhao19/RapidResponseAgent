import { useMemo, useState } from "react";
import type { AoiDetail, AssessmentJob, VlmArbitrationResult, VlmReviewMode } from "../api/client";
import { dataAssetUrl } from "../api/client";

type Props = {
  detail: AoiDetail | null;
  onShowBuildingOnMap?: (bldId: string) => void;
  onRunVlm?: (mode: VlmReviewMode, options?: { damagedOnly?: boolean }) => void;
  onStopVlm?: () => void;
  vlmJob?: AssessmentJob | null;
  vlmBusy?: boolean;
};

type TabId = "discrepancy" | "damage";

const KIND_LABELS: Record<string, string> = {
  fp_orphan: "ViPDE outside official map",
  fn_inferred: "Official footprint, weak ViPDE",
  damage_predicted: "Pipeline predicted damaged",
};

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind.replace(/_/g, " ");
}

function presentLabel(buildingPresent: unknown, needsFieldCheck?: boolean): string {
  if (needsFieldCheck) return "Needs field check";
  if (buildingPresent === true || buildingPresent === "true") return "Building";
  if (buildingPresent === false || buildingPresent === "false") return "Not a building";
  return "Uncertain";
}

function damageLabel(buildingDamaged: unknown, needsFieldCheck?: boolean): string {
  if (needsFieldCheck) return "Needs field check";
  if (buildingDamaged === true || buildingDamaged === "true") return "Damaged";
  if (buildingDamaged === false || buildingDamaged === "false") return "Not damaged";
  return "Uncertain";
}

function badgeClass(positive: boolean | null, needsFieldCheck?: boolean): string {
  if (needsFieldCheck || positive == null) return "vlm-badge vlm-badge-uncertain";
  return positive ? "vlm-badge vlm-badge-yes" : "vlm-badge vlm-badge-no";
}

function coerceBool(value: unknown): boolean | null {
  if (value === true || value === "true") return true;
  if (value === false || value === "false") return false;
  return null;
}

function formatVoteSummary(row: VlmArbitrationResult): string | null {
  const ensemble = row.ensemble;
  if (!ensemble?.enabled || !ensemble.vote_counts || !ensemble.winning_recommendation) {
    return null;
  }
  const winner = ensemble.winning_recommendation.replace(/_/g, " ");
  const winnerVotes = ensemble.vote_counts[ensemble.winning_recommendation] ?? 0;
  const total = ensemble.successful_views ?? ensemble.view_count ?? winnerVotes;
  return `${winnerVotes}/${total} views → ${winner}`;
}

function MapLink({
  bldId,
  onShowBuildingOnMap,
}: {
  bldId: string;
  onShowBuildingOnMap?: (bldId: string) => void;
}) {
  if (!onShowBuildingOnMap || !bldId) return null;
  return (
    <button
      type="button"
      className="hospital-map-btn vlm-map-btn"
      onClick={() => onShowBuildingOnMap(bldId)}
    >
      Map
    </button>
  );
}

function DiscrepancyCard({
  row,
  onShowBuildingOnMap,
}: {
  row: VlmArbitrationResult;
  onShowBuildingOnMap?: (bldId: string) => void;
}) {
  const preUrl = row.pre_chip_url ? dataAssetUrl(row.pre_chip_url) : null;
  const judgment = row.vlm;
  const description = judgment?.short_description?.trim();
  const rationale = judgment?.rationale?.trim();
  const needsCheck = Boolean(judgment?.needs_field_check);
  const present = coerceBool(judgment?.building_present);
  const voteSummary = formatVoteSummary(row);

  return (
    <article className="vlm-result-card">
      <header className="vlm-result-header">
        <div>
          <div className="vlm-result-title-row">
            <h3 className="vlm-result-id">{row.feature_id}</h3>
            <MapLink bldId={row.feature_id} onShowBuildingOnMap={onShowBuildingOnMap} />
          </div>
          <p className="vlm-result-kind">{kindLabel(row.kind)}</p>
          {voteSummary && <p className="vlm-vote-summary">{voteSummary}</p>}
        </div>
        {judgment && (
          <span className={badgeClass(present, needsCheck)}>
            {presentLabel(judgment.building_present, needsCheck)}
          </span>
        )}
      </header>

      {preUrl && (
        <figure className="vlm-chip-figure vlm-chip-single">
          <img src={preUrl} alt={`Pre-disaster RS chip ${row.feature_id}`} loading="lazy" />
          <figcaption>Pre-disaster remote sensing</figcaption>
        </figure>
      )}

      {description && <p className="vlm-description">{description}</p>}

      {rationale && (
        <section className="vlm-rationale-block">
          <h4 className="vlm-section-title">Rationale</h4>
          <p className="vlm-rationale">{rationale}</p>
        </section>
      )}

      {row.dry_run ? (
        <p className="stats-note">Dry run — candidate selected, VLM not invoked.</p>
      ) : row.error ? (
        <p className="vlm-error">VLM error: {row.error}</p>
      ) : judgment?.recommendation ? (
        <dl className="vlm-meta">
          <div>
            <dt>Recommendation</dt>
            <dd>{judgment.recommendation.replace(/_/g, " ")}</dd>
          </div>
        </dl>
      ) : null}
    </article>
  );
}

function DamageCard({
  row,
  onShowBuildingOnMap,
}: {
  row: VlmArbitrationResult;
  onShowBuildingOnMap?: (bldId: string) => void;
}) {
  const preUrl = row.pre_chip_url ? dataAssetUrl(row.pre_chip_url) : null;
  const postUrl = row.post_chip_url ? dataAssetUrl(row.post_chip_url) : null;
  const judgment = row.vlm;
  const preDesc = judgment?.pre_description?.trim();
  const postDesc = judgment?.post_description?.trim();
  const rationale = judgment?.rationale?.trim();
  const needsCheck = Boolean(judgment?.needs_field_check);
  const damaged = coerceBool(judgment?.building_damaged);
  const pipelineLabel = row.damage_label ?? (row.properties?.damage_label as string | undefined);
  const voteSummary = formatVoteSummary(row);

  return (
    <article className="vlm-result-card">
      <header className="vlm-result-header">
        <div>
          <div className="vlm-result-title-row">
            <h3 className="vlm-result-id">{row.feature_id}</h3>
            <MapLink bldId={row.feature_id} onShowBuildingOnMap={onShowBuildingOnMap} />
          </div>
          <p className="vlm-result-kind">
            {kindLabel(row.kind)}
            {pipelineLabel ? ` · pipeline: ${pipelineLabel.replace(/_/g, " ")}` : ""}
          </p>
          {voteSummary && <p className="vlm-vote-summary">{voteSummary}</p>}
        </div>
        {judgment && (
          <span className={badgeClass(damaged == null ? null : !damaged, needsCheck)}>
            {damageLabel(judgment.building_damaged, needsCheck)}
          </span>
        )}
      </header>

      {(preUrl || postUrl) && (
        <div className="vlm-chip-row">
          {preUrl && (
            <figure className="vlm-chip-figure">
              <img src={preUrl} alt={`Pre chip ${row.feature_id}`} loading="lazy" />
              <figcaption>Pre-disaster</figcaption>
            </figure>
          )}
          {postUrl && (
            <figure className="vlm-chip-figure">
              <img src={postUrl} alt={`Post chip ${row.feature_id}`} loading="lazy" />
              <figcaption>Post-disaster</figcaption>
            </figure>
          )}
        </div>
      )}

      {preDesc && (
        <section className="vlm-rationale-block">
          <h4 className="vlm-section-title">Pre description</h4>
          <p className="vlm-description">{preDesc}</p>
        </section>
      )}

      {postDesc && (
        <section className="vlm-rationale-block">
          <h4 className="vlm-section-title">Post description</h4>
          <p className="vlm-description">{postDesc}</p>
        </section>
      )}

      {rationale && (
        <section className="vlm-rationale-block">
          <h4 className="vlm-section-title">Rationale</h4>
          <p className="vlm-rationale">{rationale}</p>
        </section>
      )}

      {row.dry_run ? (
        <p className="stats-note">Dry run — candidate selected, VLM not invoked.</p>
      ) : row.error ? (
        <p className="vlm-error">VLM error: {row.error}</p>
      ) : judgment?.recommendation ? (
        <dl className="vlm-meta">
          <div>
            <dt>Recommendation</dt>
            <dd>{judgment.recommendation.replace(/_/g, " ")}</dd>
          </div>
        </dl>
      ) : null}
    </article>
  );
}

export function VlmArbitrationPanel({
  detail,
  onShowBuildingOnMap,
  onRunVlm,
  onStopVlm,
  vlmJob = null,
  vlmBusy = false,
}: Props) {
  const discrepancy = detail?.vlm_arbitration;
  const damage = detail?.vlm_damage_review;
  const discrepancyResults = discrepancy?.results ?? [];
  const damageResults = damage?.results ?? [];

  const availableTabs = useMemo(() => {
    const tabs: { id: TabId; label: string; count: number }[] = [];
    if (discrepancyResults.length > 0) {
      tabs.push({ id: "discrepancy", label: "Footprint review", count: discrepancyResults.length });
    }
    if (damageResults.length > 0) {
      tabs.push({ id: "damage", label: "Damage review", count: damageResults.length });
    }
    return tabs;
  }, [discrepancyResults.length, damageResults.length]);

  const [tab, setTab] = useState<TabId | null>(null);
  const [damagedOnly, setDamagedOnly] = useState(true);
  const activeTab = tab && availableTabs.some((item) => item.id === tab)
    ? tab
    : availableTabs[0]?.id ?? null;

  const hasResults = availableTabs.length > 0;
  const jobFailed = vlmJob?.status === "failed";
  const jobCancelled = vlmJob?.status === "cancelled";
  const jobRunning =
    vlmBusy ||
    (vlmJob != null &&
      (vlmJob.status === "queued" || vlmJob.status === "running" || vlmJob.status === "aligning"));

  const runControls = onRunVlm ? (
    <div className="vlm-run-bar">
      <div className="vlm-run-actions">
        <button
          type="button"
          className="vlm-run-btn vlm-run-btn-primary"
          disabled={jobRunning}
          onClick={() => onRunVlm("both", { damagedOnly })}
        >
          {hasResults ? "Re-run VLM" : "Run VLM"}
        </button>
        <button
          type="button"
          className="vlm-run-btn"
          disabled={jobRunning}
          onClick={() => onRunVlm("discrepancy", { damagedOnly })}
        >
          Footprints
        </button>
        <button
          type="button"
          className="vlm-run-btn"
          disabled={jobRunning}
          onClick={() => onRunVlm("damage", { damagedOnly })}
        >
          Damage
        </button>
        {jobRunning && onStopVlm ? (
          <button type="button" className="vlm-run-btn vlm-run-btn-stop" onClick={onStopVlm}>
            Stop
          </button>
        ) : null}
      </div>
      <label className="vlm-run-option">
        <input
          type="checkbox"
          checked={damagedOnly}
          disabled={jobRunning}
          onChange={(event) => setDamagedOnly(event.target.checked)}
        />
        Footprints: damaged discrepancies only
        <span className="vlm-run-option-hint">
          (skip no_damage / no_damage_inferred)
        </span>
      </label>
      {vlmJob && (
        <p
          className={`vlm-run-status${jobFailed ? " vlm-run-status-error" : ""}${
            jobCancelled ? " vlm-run-status-cancelled" : ""
          }`}
        >
          {jobRunning
            ? "Running… "
            : jobFailed
              ? "Failed — "
              : jobCancelled
                ? "Stopped — "
                : "Done — "}
          {vlmJob.message || vlmJob.status}
          {vlmJob.errors?.length ? `: ${vlmJob.errors[0]}` : null}
        </p>
      )}
    </div>
  ) : null;

  if (!hasResults) {
    return (
      <div className="vlm-panel">
        {runControls}
        <p className="stats-note">
          No VLM building review yet. Use <strong>Run VLM</strong> on this past assessment to verify
          footprint detections and predicted damage with Vision.
        </p>
      </div>
    );
  }

  const showingDamage = activeTab === "damage";
  const results = showingDamage ? damageResults : discrepancyResults;
  const fp = discrepancy?.counts_by_kind?.fp_orphan ?? 0;
  const fn = discrepancy?.counts_by_kind?.fn_inferred ?? 0;
  const damagedVotes = damage?.counts_by_recommendation?.damaged ?? 0;
  const notDamagedVotes = damage?.counts_by_recommendation?.not_damaged ?? 0;

  return (
    <div className="vlm-panel">
      {runControls}

      {availableTabs.length > 1 && (
        <div className="vlm-tabs" role="tablist" aria-label="VLM review modes">
          {availableTabs.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={activeTab === item.id}
              className={activeTab === item.id ? "vlm-tab vlm-tab-active" : "vlm-tab"}
              onClick={() => setTab(item.id)}
            >
              {item.label} ({item.count})
            </button>
          ))}
        </div>
      )}

      <p className="stats-note">
        {showingDamage ? (
          <>
            VLM reviews <strong>pre + post</strong> chips for buildings already labeled{" "}
            <code>destroyed</code>: 6 paired geometric views vote on recommendation, then the model
            synthesizes final pre/post descriptions and rationale on the original pair. Buildings
            rejected in footprint review are skipped.
            {damage?.ensemble_enabled === false ? " Last run used single-view mode." : null}
            {damage?.dry_run ? " Last run was dry-run (no VLM calls)." : null}
          </>
        ) : (
          <>
            VLM reviews <strong>pre-disaster</strong> chips for footprint discrepancies with an
            augmented-view ensemble, then synthesizes a final description and rationale.
            {discrepancy?.dry_run ? " Last run was dry-run (no VLM calls)." : null}
          </>
        )}
      </p>

      <div className="vlm-summary-row">
        <span>{results.length} reviewed</span>
        {showingDamage ? (
          <>
            <span>pre + post</span>
            {damagedVotes > 0 && <span>{damagedVotes} confirm damaged</span>}
            {notDamagedVotes > 0 && <span>{notDamagedVotes} not damaged</span>}
          </>
        ) : (
          <>
            <span>pre imagery</span>
            {fp > 0 && <span>{fp} outside-map</span>}
            {fn > 0 && <span>{fn} weak-signal footprints</span>}
          </>
        )}
        {(showingDamage ? damage?.created_at : discrepancy?.created_at) && (
          <span className="vlm-timestamp">
            Updated{" "}
            {(showingDamage ? damage!.created_at! : discrepancy!.created_at!)
              .slice(0, 19)
              .replace("T", " ")}{" "}
            UTC
          </span>
        )}
      </div>

      <div className="vlm-results">
        {results.map((row) =>
          showingDamage ? (
            <DamageCard
              key={`dmg-${row.feature_id}`}
              row={row}
              onShowBuildingOnMap={onShowBuildingOnMap}
            />
          ) : (
            <DiscrepancyCard
              key={`disc-${row.feature_id}`}
              row={row}
              onShowBuildingOnMap={onShowBuildingOnMap}
            />
          ),
        )}
      </div>
    </div>
  );
}
