/-
  CertBrief.Action — the deterministic ops recommendation per grid cell.

  Mirrors the recommendation rule of the `geoagent` package (available by request; see the repository README).
  Ratios are cross-multiplied so everything is exact Nat arithmetic:
      destroyed / total >= 0.12              ↦  100 * d      ≥ 12 * t
      (destroyed + major) / total >= 0.25    ↦  100 * (d+ma) ≥ 25 * t
  with t = max(total, 1) as in the reference implementation. Agreement of the float and
  integer forms is established by differential testing, not assumed.
-/
import CertBrief.Basic

namespace CertBrief

inductive Action where
  | rapidInspection    -- "Rapid inspection"
  | fireSuppression    -- "Fire suppression / hazard control"
  | searchRescue       -- "Immediate Search & Rescue"
  deriving DecidableEq, Repr

/-- Operational severity: SAR > fire/hazard > rapid inspection. -/
def Action.severity : Action → Nat
  | .rapidInspection => 0
  | .fireSuppression => 1
  | .searchRescue    => 2

/-- Faithful transcription of the reference rule order. -/
def recommend (c : Counts) : Action :=
  let t  := max c.total 1
  let d  := c.destroyed
  let ma := c.major
  let mi := c.minor
  if d ≥ 5 ∨ 100 * d ≥ 12 * t ∨ (d ≥ 2 ∧ c.impact ≥ 12) then .searchRescue
  else if ma ≥ 5 ∨ 100 * (d + ma) ≥ 25 * t ∨ ma + d ≥ 8 then .fireSuppression
  else if mi ≥ ma + d ∧ mi ≥ 3 then .rapidInspection
  else if c.impact ≥ 10 then .searchRescue
  else if ma + d ≥ 1 then .fireSuppression
  else .rapidInspection

/-! ### T4 — safety properties that DO hold -/

/-- T4a: five or more destroyed buildings always trigger Search & Rescue. -/
theorem sar_of_destroyed_ge5 (c : Counts) (h : c.destroyed ≥ 5) :
    recommend c = .searchRescue := by
  simp [recommend, h]

/-- T4b: a cell with no damage is only ever sent a rapid inspection. -/
theorem rapid_of_undamaged (c : Counts) (h : c.damaged = 0) :
    recommend c = .rapidInspection := by
  obtain ⟨nd, mi, ma, de⟩ := c
  simp only [Counts.damaged] at h
  have h1 : mi = 0 := by omega
  have h2 : ma = 0 := by omega
  have h3 : de = 0 := by omega
  subst h1 h2 h3
  simp [recommend, Counts.impact, Counts.total,
    show 12 * max nd 1 ≠ 0 by omega, show 25 * max nd 1 ≠ 0 by omega]

/-- T4c: ≥ 12 % destroyed always triggers SAR (the share rule is never shadowed). -/
theorem sar_of_destroyed_share (c : Counts) (h : 100 * c.destroyed ≥ 12 * max c.total 1) :
    recommend c = .searchRescue := by
  simp only [recommend]
  split
  · rfl
  · exfalso; omega

/-! ### T4 — a property that does NOT hold

  Monotonicity: "one building getting worse never lowers the recommended response."
  Witnesses:
    (nd, mi, ma, de) = (2, 2, 1, 0) fire → (1, 3, 1, 0) rapid   [no_damage → minor]
    (2, 14, 5, 0) fire → (2, 14, 4, 1) rapid                     [major → destroyed]
    (10, 3, 3, 1) SAR  → (10, 2, 4, 1) fire                      [minor → major]
  Cause: the "minor-dominant ⇒ rapid inspection" rule precedes "impact ≥ 10 ⇒ SAR"
  and shadows the ma+d ≥ 1 ⇒ fire fallback.
-/

/-- `severity` commutes with `if` (lets `split` reach the conditions). -/
theorem severity_ite (p : Prop) [Decidable p] (a b : Action) :
    (if p then a else b).severity = if p then a.severity else b.severity := by
  split <;> rfl

def Monotone (f : Counts → Action) : Prop :=
  ∀ c c' l, c.upgrade l = some c' → (f c).severity ≤ (f c').severity

/-- Counterexample, checked by evaluation (`decide`) — no `sorry`. -/
theorem recommend_not_monotone : ¬ Monotone recommend := by
  intro h
  have := h ⟨2, 14, 5, 0⟩ ⟨2, 14, 4, 1⟩ .major (by decide)
  exact absurd this (by decide)

/-- Witnesses spelled out (also decidable). -/
example : recommend ⟨2, 14, 5, 0⟩ = .fireSuppression := by decide
example : recommend ⟨2, 14, 4, 1⟩ = .rapidInspection := by decide
example : recommend ⟨10, 3, 3, 1⟩ = .searchRescue := by decide
example : recommend ⟨10, 2, 4, 1⟩ = .fireSuppression := by decide

/-! ### Candidate monotone variant (not the deployed rule)

  Evaluate every SAR trigger first, then any severe damage ⇒ fire, else rapid.
  Changes behaviour: minor-dominant cells with impact ≥ 10 become SAR, and any
  cell with ≥ 1 major/destroyed is never sent only a rapid inspection.
-/
/-- Every SAR trigger of the candidate rule, as one proposition. -/
def sarCond (c : Counts) : Prop :=
  c.destroyed ≥ 5 ∨ 100 * c.destroyed ≥ 12 * max c.total 1 ∨
    (c.destroyed ≥ 2 ∧ c.impact ≥ 12) ∨ c.impact ≥ 10

instance : DecidablePred sarCond := fun c => by unfold sarCond; exact inferInstance

def recommendMono (c : Counts) : Action :=
  if sarCond c then .searchRescue
  else if c.major + c.destroyed ≥ 1 then .fireSuppression
  else .rapidInspection

/-- SAR triggers survive any single-level upgrade. -/
theorem sarCond_upgrade {c c' : Counts} {l : Level} (h : c.upgrade l = some c') :
    sarCond c → sarCond c' := by
  obtain ⟨nd, mi, ma, de⟩ := c
  cases l <;> simp only [Counts.upgrade] at h <;> (try split at h) <;> simp at h
  all_goals (subst h; simp only [sarCond, Counts.impact, Counts.total]; omega)

/-- "Some severe damage" survives any single-level upgrade. -/
theorem severe_upgrade {c c' : Counts} {l : Level} (h : c.upgrade l = some c') :
    c.major + c.destroyed ≥ 1 → c'.major + c'.destroyed ≥ 1 := by
  obtain ⟨nd, mi, ma, de⟩ := c
  cases l <;> simp only [Counts.upgrade] at h <;> (try split at h) <;> simp at h
  all_goals (subst h; simp only; omega)

theorem recommendMono_monotone : Monotone recommendMono := by
  intro c c' l h
  have hs := sarCond_upgrade h
  have hf := severe_upgrade h
  unfold recommendMono
  by_cases a : sarCond c <;> by_cases b : sarCond c' <;>
    by_cases x : c.major + c.destroyed ≥ 1 <;> by_cases y : c'.major + c'.destroyed ≥ 1 <;>
    simp_all [Action.severity]

/-- The candidate keeps the T4a/T4b safety properties. -/
theorem recommendMono_sar_of_destroyed_ge5 (c : Counts) (h : c.destroyed ≥ 5) :
    recommendMono c = .searchRescue := by
  simp [recommendMono, sarCond, h]

end CertBrief
