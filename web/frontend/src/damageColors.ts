/**
 * ViPDE damage colors — keep in sync with perception/vipde/utils/visualize.py DAMAGE_COLORMAP
 *
 * Level 1 No Damage:  rgb(0, 255, 0)   -> #00FF00
 * Level 2 Minor:      rgb(1, 191, 134) -> #01BF86
 * Level 3 Major:      rgb(1, 191, 254) -> #01BFFE
 * Level 4 Destroyed:  rgb(251, 12, 4)  -> #FB0C04
 *
 * Map display folds `no_damage_inferred` into `no_damage` (same color/label).
 * Pipeline data still keeps assignment_status / no_damage_inferred internally.
 */
export const VIPDE_DAMAGE_COLORS = {
  no_damage: "#00FF00",
  minor: "#01BF86",
  major: "#01BFFE",
  destroyed: "#FB0C04",
  unknown: "#94a3b8",
} as const;

/** Map / legend taxonomy: four display classes only. */
export function displayDamageLabel(label: string | null | undefined): string {
  const raw = String(label ?? "unknown");
  if (raw === "no_damage_inferred") return "no_damage";
  return raw;
}

export function damageColor(label: string): string {
  switch (displayDamageLabel(label)) {
    case "no_damage":
      return VIPDE_DAMAGE_COLORS.no_damage;
    case "minor":
      return VIPDE_DAMAGE_COLORS.minor;
    case "major":
      return VIPDE_DAMAGE_COLORS.major;
    case "destroyed":
      return VIPDE_DAMAGE_COLORS.destroyed;
    default:
      return VIPDE_DAMAGE_COLORS.unknown;
  }
}

export function damageColorByLevel(level: number | null | undefined): string {
  switch (level) {
    case 1:
      return VIPDE_DAMAGE_COLORS.no_damage;
    case 2:
      return VIPDE_DAMAGE_COLORS.minor;
    case 3:
      return VIPDE_DAMAGE_COLORS.major;
    case 4:
      return VIPDE_DAMAGE_COLORS.destroyed;
    default:
      return VIPDE_DAMAGE_COLORS.unknown;
  }
}
