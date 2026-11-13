/-
  CertBrief.Policy — agent-action policy at the tool-execution boundary.

  Mirrors the tool-execution policy of the `geoagent` package (available by request; see the repository README).

  Policies (see the repository README):
    P1  multi-tool plans pause for an explicit yes/no confirm before running;
    P2  the executed tools are the ones the user confirmed (no silent additions);
    P3  operational numbers come from case-data tools, never from SOP guidance;
    P4  every numeric claim is sourced from the session's active AOI.

  P1/P2 also catch time-of-check/time-of-use gaps: if a confirm gate checks one plan and
  the execution layer later adds tools, `checkPolicy` rejects the turn (first example below).

  AOI ids are interned to Nat by the caller (keeps `decide` kernel-friendly).
-/

namespace CertBrief

inductive Tool where
  | damageStats | missionPriority | hospitals | facilities
  | weather | roads | historical | report | guidance
  deriving DecidableEq, Repr

/-- answer_policy.CASE_DATA_TOOLS vs GUIDANCE_TOOLS. -/
def Tool.isCaseData : Tool → Bool
  | .guidance => false
  | _         => true

structure Call where
  tool : Tool
  aoi  : Option Nat
  deriving DecidableEq, Repr

/-- Where a numeric claim in the brief came from. -/
structure Source where
  tool : Tool
  aoi  : Option Nat
  deriving DecidableEq, Repr

/-- Everything the boundary check sees for one chat turn. -/
structure Turn where
  activeAoi : Option Nat
  /-- The tool list shown to the user in the confirm card (or the single planned tool). -/
  gated     : List Tool
  /-- User replied "yes" to exactly `gated`. -/
  confirmed : Bool
  executed  : List Call
  sources   : List Source
  deriving Repr

def Policy (t : Turn) : Prop :=
  -- P1 + P2
  (t.executed.length > 1 → t.confirmed = true) ∧
  (∀ c ∈ t.executed, c.tool ∈ t.gated) ∧
  -- P3 + P4 (+ the source was actually executed this turn)
  (∀ s ∈ t.sources, s.tool.isCaseData = true ∧ s.aoi = t.activeAoi ∧
      Call.mk s.tool s.aoi ∈ t.executed)

def checkPolicy (t : Turn) : Bool :=
  (decide (t.executed.length ≤ 1) || t.confirmed) &&
  t.executed.all (fun c => t.gated.contains c.tool) &&
  t.sources.all (fun s => s.tool.isCaseData && s.aoi == t.activeAoi &&
      t.executed.contains (Call.mk s.tool s.aoi))

/-- T6: the policy checker is sound. -/
theorem checkPolicy_sound (t : Turn) (h : checkPolicy t = true) : Policy t := by
  simp only [checkPolicy, Bool.and_eq_true, Bool.or_eq_true, decide_eq_true_eq,
    List.all_eq_true, List.contains_iff_mem, beq_iff_eq] at h
  obtain ⟨⟨h1, h2⟩, h3⟩ := h
  refine ⟨?_, h2, ?_⟩
  · intro hlen
    rcases h1 with h1 | h1
    · omega
    · exact h1
  · intro s hs
    have := h3 s hs
    exact ⟨this.1.1, this.1.2, this.2⟩

/-- …and complete: every policy-respecting turn is accepted. -/
theorem checkPolicy_complete (t : Turn) (h : Policy t) : checkPolicy t = true := by
  obtain ⟨h1, h2, h3⟩ := h
  simp only [checkPolicy, Bool.and_eq_true, Bool.or_eq_true, decide_eq_true_eq,
    List.all_eq_true, List.contains_iff_mem, beq_iff_eq]
  refine ⟨⟨?_, h2⟩, ?_⟩
  · by_cases hl : t.executed.length ≤ 1
    · exact Or.inl hl
    · exact Or.inr (h1 (by omega))
  · intro s hs
    obtain ⟨a, b, c⟩ := h3 s hs
    exact ⟨⟨a, b⟩, c⟩

/-- A tool added after the confirm gate (time-of-check ≠ time-of-use) is rejected. -/
example : checkPolicy
    { activeAoi := some 0, gated := [.guidance], confirmed := false,
      executed := [⟨.damageStats, some 0⟩, ⟨.guidance, some 0⟩],
      sources := [⟨.damageStats, some 0⟩] } = false := by decide

/-- A confirmed two-tool plan that runs exactly what was confirmed is accepted. -/
example : checkPolicy
    { activeAoi := some 0, gated := [.damageStats, .guidance], confirmed := true,
      executed := [⟨.damageStats, some 0⟩, ⟨.guidance, some 0⟩],
      sources := [⟨.damageStats, some 0⟩] } = true := by decide

/-- A number sourced from SOP guidance is rejected (P3). -/
example : checkPolicy
    { activeAoi := some 0, gated := [.guidance], confirmed := false,
      executed := [⟨.guidance, some 0⟩],
      sources := [⟨.guidance, some 0⟩] } = false := by decide

/-- A number from a different AOI is rejected (P4). -/
example : checkPolicy
    { activeAoi := some 0, gated := [.damageStats], confirmed := false,
      executed := [⟨.damageStats, some 1⟩],
      sources := [⟨.damageStats, some 1⟩] } = false := by decide

end CertBrief
