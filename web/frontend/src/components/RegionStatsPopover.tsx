import { damageColor } from "../damageColors";
import {
  DAMAGE_LABEL_DISPLAY,
  DAMAGE_LABEL_ORDER,
  pct,
  type RegionDamageStats,
} from "../regionStats";

type Props = {
  stats: RegionDamageStats;
  anchor: { x: number; y: number };
  onClose: () => void;
};

export function RegionStatsPopover({ stats, anchor, onClose }: Props) {
  const rows = DAMAGE_LABEL_ORDER.map((label) => ({
    label,
    count: stats.byLabel[label] ?? 0,
  })).filter((row) => row.count > 0);

  return (
    <div
      className="region-stats-popover"
      style={{ left: anchor.x, top: anchor.y }}
      role="dialog"
      aria-label="Selection summary"
    >
      <div className="region-stats-popover-header">
        <strong>Selection summary</strong>
        <button type="button" className="region-stats-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      <div className="region-stats-total">
        <span>Total buildings</span>
        <strong>{stats.total}</strong>
      </div>
      {stats.total === 0 ? (
        <p className="region-stats-empty">No buildings in this area.</p>
      ) : (
        <ul className="region-stats-list">
          {rows.map((row) => (
            <li key={row.label}>
              <span className="region-stats-swatch" style={{ background: damageColor(row.label) }} />
              <span className="region-stats-label">{DAMAGE_LABEL_DISPLAY[row.label] ?? row.label}</span>
              <span className="region-stats-count">
                {row.count} <em>({pct(row.count, stats.total)})</em>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
