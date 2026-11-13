/-
  CertBrief.Basic — damage levels and per-cell building counts.

  Mirrors the damage levels and grid statistics of the `geoagent` package (available by request; see the repository README).

  STATUS (2026-11-13): builds on Lean 4.35.0 with no `sorry`; every theorem in this
  library depends only on propext / Quot.sound / Classical.choice (`#print axioms`).
-/

namespace CertBrief

/-- The four effective damage levels (`no_damage_inferred` folds into `noDamage`). -/
inductive Level where
  | noDamage
  | minor
  | major
  | destroyed
  deriving DecidableEq, Repr

/-- Building counts by effective level for one grid cell (or a whole AOI). -/
structure Counts where
  noDamage  : Nat
  minor     : Nat
  major     : Nat
  destroyed : Nat
  deriving DecidableEq, Repr

namespace Counts

def zero : Counts := ⟨0, 0, 0, 0⟩

def get (c : Counts) : Level → Nat
  | .noDamage  => c.noDamage
  | .minor     => c.minor
  | .major     => c.major
  | .destroyed => c.destroyed

def total   (c : Counts) : Nat := c.noDamage + c.minor + c.major + c.destroyed
/-- DAMAGED_LABELS = minor, major, destroyed. -/
def damaged (c : Counts) : Nat := c.minor + c.major + c.destroyed
/-- SEVERE_LABELS = major, destroyed. -/
def severe  (c : Counts) : Nat := c.major + c.destroyed
/-- compute_spatial_grid_3x3: weights minor 1, major 2, destroyed 3. -/
def impact  (c : Counts) : Nat := c.minor + 2 * c.major + 3 * c.destroyed

def add (a b : Counts) : Counts :=
  ⟨a.noDamage + b.noDamage, a.minor + b.minor, a.major + b.major, a.destroyed + b.destroyed⟩

/-- Record one more building at level `l`. -/
def bump (c : Counts) : Level → Counts
  | .noDamage  => { c with noDamage  := c.noDamage + 1 }
  | .minor     => { c with minor     := c.minor + 1 }
  | .major     => { c with major     := c.major + 1 }
  | .destroyed => { c with destroyed := c.destroyed + 1 }

/-- One building moves up exactly one level (total preserved).
    `none` when no building is at the source level, or it is already destroyed. -/
def upgrade (c : Counts) : Level → Option Counts
  | .noDamage  => if c.noDamage = 0 then none
                  else some { c with noDamage := c.noDamage - 1, minor := c.minor + 1 }
  | .minor     => if c.minor = 0 then none
                  else some { c with minor := c.minor - 1, major := c.major + 1 }
  | .major     => if c.major = 0 then none
                  else some { c with major := c.major - 1, destroyed := c.destroyed + 1 }
  | .destroyed => none

/-! ### T1/T2 — conservation and monotonicity of the data layer -/

/-- T1a: recording a building adds exactly one to the total. -/
theorem total_bump (c : Counts) (l : Level) : (c.bump l).total = c.total + 1 := by
  cases l <;> simp [bump, total] <;> omega

/-- T1b: an upgrade never changes the number of buildings. -/
theorem total_upgrade {c c' : Counts} {l : Level} (h : c.upgrade l = some c') :
    c'.total = c.total := by
  obtain ⟨nd, mi, ma, de⟩ := c
  cases l <;> simp only [upgrade] at h <;> (try split at h) <;> simp at h
  all_goals (subst h; simp only [total]; omega)

/-- T1c: totals are additive (AOI total = sum of the nine cells). -/
theorem total_add (a b : Counts) : (a.add b).total = a.total + b.total := by
  simp only [add, total]; omega

/-- T2a: any single-level upgrade strictly increases impact. -/
theorem impact_upgrade_lt {c c' : Counts} {l : Level} (h : c.upgrade l = some c') :
    c.impact < c'.impact := by
  obtain ⟨nd, mi, ma, de⟩ := c
  cases l <;> simp only [upgrade] at h <;> (try split at h) <;> simp at h
  all_goals (subst h; simp only [impact]; omega)

/-- T2b: impact is at most three points per building. -/
theorem impact_le (c : Counts) : c.impact ≤ 3 * c.total := by
  unfold impact total; omega

theorem damaged_le_total (c : Counts) : c.damaged ≤ c.total := by
  unfold damaged total; omega

end Counts
end CertBrief
