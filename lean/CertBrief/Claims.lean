/-
  CertBrief.Claims — claims extracted from an LLM brief, their meaning (`Holds`),
  and the executable checker (`check`) with its soundness theorem (T5).

  Honest scope note: for count/total/action claims `Holds` is close to the checker
  by construction, so soundness is shallow there. The non-trivial cases are
  `priority` (declarative ranking spec vs. computed sort, via T3) and `pct`
  (rounding semantics). Claim extraction from free text and the tool facts themselves
  are outside the proofs (tested, not proved).
-/
import CertBrief.Grid
import CertBrief.Action

namespace CertBrief

inductive Scope where
  | aoi
  | cell (d : Dir)
  deriving DecidableEq, Repr

/-- One atomic, checkable statement found in a brief. -/
inductive Claim where
  /-- "N buildings at level L" in scope S. -/
  | count (s : Scope) (l : Level) (n : Nat)
  /-- "N buildings in total" in scope S. -/
  | total (s : Scope) (n : Nat)
  /-- "N damaged" (minor + major + destroyed) in scope S. -/
  | damaged (s : Scope) (n : Nat)
  /-- "impact N" in scope S. -/
  | impact (s : Scope) (n : Nat)
  /-- "P % at level L", P written as mantissa / 10^decimals (e.g. 37.0 ↦ 370, 1). -/
  | pct (s : Scope) (l : Level) (mantissa decimals : Nat)
  /-- "Priority k is direction d" (k is 1-based). -/
  | priority (k : Nat) (d : Dir)
  /-- "Recommended action for d is a". -/
  | action (d : Dir) (a : Action)
  deriving DecidableEq, Repr

/-- Tool facts the claims are checked against. `aoi` is kept separate from the grid
    sum because buildings with empty geometry are skipped when binning. -/
structure Facts where
  aoi  : Counts
  grid : Grid

def Facts.counts (f : Facts) : Scope → Counts
  | .aoi    => f.aoi
  | .cell d => f.grid d

/-- Stated P = m / 10^k is a correct rounding of the true share 100·n/t to k decimals:
      |m/10^k − 100·n/t| ≤ ½·10^-k   ⇔   |2·m·t − 200·n·10^k| ≤ t   (t > 0). -/
def PctOk (n t m k : Nat) : Prop :=
  t > 0 ∧ Int.natAbs (2 * (m : Int) * t - 200 * (n : Int) * (10 ^ k : Nat)) ≤ t

instance (n t m k : Nat) : Decidable (PctOk n t m k) := by
  unfold PctOk; exact inferInstance

/-- Meaning of a claim — written independently of the checker. -/
def Holds (f : Facts) : Claim → Prop
  | .count s l n      => (f.counts s).get l = n
  | .total s n        => (f.counts s).total = n
  | .damaged s n      => (f.counts s).damaged = n
  | .impact s n       => (f.counts s).impact = n
  | .pct s l m k      => PctOk ((f.counts s).get l) (f.counts s).total m k
  | .priority k d     => ∃ r, IsRanking f.grid r ∧ r[k - 1]? = some d ∧ k ≥ 1
  | .action d a       => recommend (f.grid d) = a

/-- Executable checker (this is what the compiled binary runs). -/
def check (f : Facts) : Claim → Bool
  | .count s l n      => (f.counts s).get l == n
  | .total s n        => (f.counts s).total == n
  | .damaged s n      => (f.counts s).damaged == n
  | .impact s n       => (f.counts s).impact == n
  | .pct s l m k      => decide (PctOk ((f.counts s).get l) (f.counts s).total m k)
  | .priority k d     => decide (k ≥ 1) && (rank f.grid)[k - 1]? == some d
  | .action d a       => recommend (f.grid d) == a

/-- T5: the checker is sound — accepted claims are true of the facts. -/
theorem check_sound (f : Facts) (c : Claim) (h : check f c = true) : Holds f c := by
  cases c
  case priority k d =>
    simp only [check, Bool.and_eq_true, decide_eq_true_eq, beq_iff_eq] at h
    exact ⟨rank f.grid, rank_isRanking f.grid, h.2, h.1⟩
  all_goals simpa [check, Holds] using h

/-- T5': and complete — true claims are accepted (uses isRanking_unique, T3c). -/
theorem check_complete (f : Facts) (c : Claim) (h : Holds f c) : check f c = true := by
  cases c
  case priority k d =>
    obtain ⟨r, hr, hget, hk⟩ := h
    rw [isRanking_unique f.grid r hr] at hget
    simp only [check, Bool.and_eq_true, decide_eq_true_eq, beq_iff_eq]
    exact ⟨hk, hget⟩
  all_goals simpa [check, Holds] using h

/-- A brief is certified iff every extracted claim checks. -/
def certify (f : Facts) (cs : List Claim) : Bool := cs.all (check f)

theorem certify_sound (f : Facts) (cs : List Claim) (h : certify f cs = true) :
    ∀ c ∈ cs, Holds f c := by
  intro c hc
  simp only [certify, List.all_eq_true] at h
  exact check_sound f c (h c hc)

/-- Data-integrity claim (T1 applied to tool output): grid cells sum to the AOI. -/
def gridConsistent (f : Facts) : Bool := f.grid.sum == f.aoi

end CertBrief
