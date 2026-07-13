import {
  BUILDING_SCOPE_HINTS,
  BUILDING_SCOPE_LABELS,
  type BuildingScope,
} from "../buildingScope";

type Props = {
  value: BuildingScope;
  onChange: (scope: BuildingScope) => void;
  showFused: boolean;
  showVlm?: boolean;
  /** Keep dual-button layout while AOI detail is still loading. */
  pending?: boolean;
};

export function BuildingScopeToggle({
  value,
  onChange,
  showFused,
  showVlm = false,
  pending = false,
}: Props) {
  const scopes: BuildingScope[] = ["official"];
  if (showFused || pending) scopes.push("fused");
  if (showVlm) scopes.push("vlm");

  if (scopes.length === 1) {
    return (
      <span className="building-scope-badge" title={BUILDING_SCOPE_HINTS.official}>
        {BUILDING_SCOPE_LABELS.official}
      </span>
    );
  }

  return (
    <div className="building-scope-toggle" role="group" aria-label="Building inventory view">
      {scopes.map((scope) => {
        const disabled = scope === "fused" && !showFused;
        return (
          <button
            key={scope}
            type="button"
            className={`building-scope-btn ${value === scope ? "active" : ""}`}
            aria-pressed={value === scope}
            aria-disabled={disabled}
            disabled={disabled}
            title={BUILDING_SCOPE_HINTS[scope]}
            onClick={() => onChange(scope)}
          >
            {BUILDING_SCOPE_LABELS[scope]}
          </button>
        );
      })}
    </div>
  );
}
