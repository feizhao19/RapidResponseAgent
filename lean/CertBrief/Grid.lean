/-
  CertBrief.Grid — north-up 3×3 directional grid and the "most affected" ranking.

  Mirrors the 3×3 grid and Mission Priority ranking of the `geoagent` package (available by request; see the repository README).

  Ranking key (reference implementation): (impact_score, damaged_count, buildings_total), sorted with
  reverse=True. Python's sort is stable, and reverse=True keeps equal keys in their
  original order, so ties are broken by SPATIAL_GRID_LABELS order (NW, N, NE, W, …).
  Cells with buildings_total = 0 are excluded. Top 3 become Priority 1–3.

  OUT OF SCOPE (trusted, tested rather than proved): mapping a building centroid (float
  lon/lat) to a cell. The Lean model starts from (row, col, level) triples.
-/
import CertBrief.Basic

namespace CertBrief

/-- Grid cells in SPATIAL_GRID_LABELS order (row 0 = north). -/
inductive Dir where
  | NW | N | NE | W | Center | E | SW | S | SE
  deriving DecidableEq, Repr

namespace Dir

def all : List Dir := [.NW, .N, .NE, .W, .Center, .E, .SW, .S, .SE]

/-- Position in SPATIAL_GRID_LABELS; used for tie-breaking. -/
def index : Dir → Nat
  | .NW => 0 | .N => 1 | .NE => 2 | .W => 3 | .Center => 4
  | .E => 5 | .SW => 6 | .S => 7 | .SE => 8

theorem mem_all (d : Dir) : d ∈ all := by cases d <;> decide

theorem index_inj {a b : Dir} (h : a.index = b.index) : a = b := by
  cases a <;> cases b <;> first | rfl | (simp [index] at h)

def ofRowCol : Fin 3 → Fin 3 → Dir
  | ⟨0, _⟩, ⟨0, _⟩ => .NW | ⟨0, _⟩, ⟨1, _⟩ => .N | ⟨0, _⟩, _ => .NE
  | ⟨1, _⟩, ⟨0, _⟩ => .W  | ⟨1, _⟩, ⟨1, _⟩ => .Center | ⟨1, _⟩, _ => .E
  | _, ⟨0, _⟩ => .SW | _, ⟨1, _⟩ => .S | _, _ => .SE

end Dir

/-- A grid assigns counts to every direction. -/
def Grid := Dir → Counts

namespace Grid

def zero : Grid := fun _ => Counts.zero

def bump (g : Grid) (d : Dir) (l : Level) : Grid :=
  fun e => if e = d then (g e).bump l else g e

/-- Sum of all nine cells. -/
def sum (g : Grid) : Counts := Dir.all.foldl (fun acc d => acc.add (g d)) Counts.zero

def total (g : Grid) : Nat := (g.sum).total

theorem total_eq (g : Grid) : g.total =
    (g .NW).total + (g .N).total + (g .NE).total + (g .W).total + (g .Center).total +
    (g .E).total + (g .SW).total + (g .S).total + (g .SE).total := by
  simp only [total, sum, Dir.all, List.foldl, Counts.total_add]
  simp only [Counts.zero, Counts.total]
  omega

theorem total_bump (g : Grid) (d : Dir) (l : Level) : (g.bump d l).total = g.total + 1 := by
  rw [total_eq, total_eq]
  cases d <;> simp [bump, Counts.total_bump] <;> omega

theorem zero_total : zero.total = 0 := by
  simp [total_eq, zero, Counts.zero, Counts.total]

end Grid

/-- A building already placed in the grid (centroid → cell is trusted, not modelled). -/
structure Building where
  row   : Fin 3
  col   : Fin 3
  level : Level

def binAll (bs : List Building) : Grid :=
  bs.foldl (fun g b => g.bump (Dir.ofRowCol b.row b.col) b.level) Grid.zero

/-- T1d: every building lands in exactly one cell — grid total = number of buildings.
    (Buildings with empty geometry are skipped upstream; `gridConsistent` checks grid vs AOI.) -/
theorem foldl_bump_total (bs : List Building) (g : Grid) :
    (bs.foldl (fun g b => g.bump (Dir.ofRowCol b.row b.col) b.level) g).total
      = g.total + bs.length := by
  induction bs generalizing g with
  | nil => simp
  | cons b bs ih =>
    simp only [List.foldl_cons, List.length_cons]
    rw [ih, Grid.total_bump]
    omega

theorem binAll_total (bs : List Building) : (binAll bs).total = bs.length := by
  unfold binAll
  rw [foldl_bump_total, Grid.zero_total]
  omega

/-! ### Ranking -/

/-- Lexicographic ranking key, as in the reference implementation. -/
def key (c : Counts) : Nat × Nat × Nat := (c.impact, c.damaged, c.total)

/-- `a` ranks strictly before `b` in grid `g` (higher key first; ties by label order). -/
def before (g : Grid) (a b : Dir) : Prop :=
  let ka := key (g a); let kb := key (g b)
  ka.1 > kb.1 ∨ (ka.1 = kb.1 ∧ (ka.2.1 > kb.2.1 ∨ (ka.2.1 = kb.2.1 ∧
    (ka.2.2 > kb.2.2 ∨ (ka.2.2 = kb.2.2 ∧ a.index < b.index)))))

instance (g : Grid) (a b : Dir) : Decidable (before g a b) := by
  unfold before; exact inferInstance

theorem before_irrefl (g : Grid) (a : Dir) : ¬ before g a a := by
  simp only [before]; omega

theorem before_trans (g : Grid) {a b c : Dir} (h1 : before g a b) (h2 : before g b c) :
    before g a c := by
  simp only [before] at *; omega

theorem before_total (g : Grid) {a b : Dir} (h : a ≠ b) : before g a b ∨ before g b a := by
  have : a.index ≠ b.index := fun e => h (Dir.index_inj e)
  simp only [before]; omega

/-- Declarative spec of the full ranking: exactly the non-empty cells, each before the next. -/
def IsRanking (g : Grid) (r : List Dir) : Prop :=
  r.Nodup ∧ (∀ d, d ∈ r ↔ (g d).total > 0) ∧ r.Pairwise (before g)

/-- Computational ranking (insertion sort) — what the runtime checker evaluates. -/
def insertBy (g : Grid) (d : Dir) : List Dir → List Dir
  | [] => [d]
  | x :: xs => if before g d x then d :: x :: xs else x :: insertBy g d xs

def rank (g : Grid) : List Dir :=
  (Dir.all.filter (fun d => decide ((g d).total > 0))).foldr (insertBy g) []

/-! ### Insertion-sort lemmas -/

theorem mem_insertBy (g : Grid) (d x : Dir) (l : List Dir) :
    x ∈ insertBy g d l ↔ x = d ∨ x ∈ l := by
  induction l with
  | nil => simp [insertBy]
  | cons y ys ih =>
    simp only [insertBy]
    split
    · simp
    · simp only [List.mem_cons, ih]
      constructor
      · rintro (h | h | h)
        · exact Or.inr (Or.inl h)
        · exact Or.inl h
        · exact Or.inr (Or.inr h)
      · rintro (h | h | h)
        · exact Or.inr (Or.inl h)
        · exact Or.inl h
        · exact Or.inr (Or.inr h)

theorem pairwise_insertBy (g : Grid) (d : Dir) (l : List Dir)
    (hl : l.Pairwise (before g)) (hd : d ∉ l) : (insertBy g d l).Pairwise (before g) := by
  induction l with
  | nil => simp [insertBy]
  | cons y ys ih =>
    have hl' := List.pairwise_cons.1 hl
    have hdy : d ≠ y := fun e => hd (by rw [e]; simp)
    have hdys : d ∉ ys := fun m => hd (List.mem_cons_of_mem _ m)
    simp only [insertBy]
    split
    · rename_i hb
      refine List.pairwise_cons.2 ⟨?_, hl⟩
      intro z hz
      rcases List.mem_cons.1 hz with rfl | hz
      · exact hb
      · exact before_trans g hb (hl'.1 z hz)
    · rename_i hb
      have hyd : before g y d := (before_total g hdy).resolve_left hb
      refine List.pairwise_cons.2 ⟨?_, ih hl'.2 hdys⟩
      intro z hz
      rcases (mem_insertBy g d z ys).1 hz with rfl | hz
      · exact hyd
      · exact hl'.1 z hz

theorem foldr_insert_props (g : Grid) (l : List Dir) (hn : l.Nodup) :
    (∀ x, x ∈ l.foldr (insertBy g) [] ↔ x ∈ l) ∧ (l.foldr (insertBy g) []).Pairwise (before g) := by
  induction l with
  | nil => simp
  | cons a as ih =>
    have hn' := List.nodup_cons.1 hn
    obtain ⟨ihm, ihp⟩ := ih hn'.2
    refine ⟨fun x => ?_, ?_⟩
    · simp only [List.foldr_cons]
      rw [mem_insertBy, ihm]
      simp
    · simp only [List.foldr_cons]
      exact pairwise_insertBy g a _ ihp (fun m => hn'.1 ((ihm a).1 m))

/-- Two strictly sorted lists with the same elements are equal. -/
theorem sorted_unique (g : Grid) : ∀ (l₁ l₂ : List Dir), l₁.Pairwise (before g) →
    l₂.Pairwise (before g) → (∀ x, x ∈ l₁ ↔ x ∈ l₂) → l₁ = l₂
  | [], [], _, _, _ => rfl
  | [], b :: _, _, _, hm => by simpa using (hm b).2 (by simp)
  | a :: _, [], _, _, hm => by simpa using (hm a).1 (by simp)
  | a :: as, b :: bs, h₁, h₂, hm => by
    have h₁' := List.pairwise_cons.1 h₁
    have h₂' := List.pairwise_cons.1 h₂
    have hab : a = b := by
      by_cases e : a = b
      · exact e
      · exfalso
        have ha : a ∈ bs := by
          have := (hm a).1 (by simp)
          simp only [List.mem_cons] at this
          exact this.resolve_left e
        have hb : b ∈ as := by
          have := (hm b).2 (by simp)
          simp only [List.mem_cons] at this
          exact this.resolve_left (Ne.symm e)
        exact before_irrefl g a (before_trans g (h₁'.1 b hb) (h₂'.1 a ha))
    subst hab
    have hna : a ∉ as := fun m => before_irrefl g a (h₁'.1 a m)
    have hnb : a ∉ bs := fun m => before_irrefl g a (h₂'.1 a m)
    rw [sorted_unique g as bs h₁'.2 h₂'.2 (fun x => by
      have := hm x
      simp only [List.mem_cons] at this
      constructor
      · intro hx
        exact (this.1 (Or.inr hx)).resolve_left (fun e => hna (e ▸ hx))
      · intro hx
        exact (this.2 (Or.inr hx)).resolve_left (fun e => hnb (e ▸ hx)))]

/-- T3a: the computed ranking satisfies the declarative spec. -/
theorem rank_isRanking (g : Grid) : IsRanking g (rank g) := by
  have hall : Dir.all.Nodup := by decide
  have hf : (Dir.all.filter (fun d => decide ((g d).total > 0))).Nodup :=
    List.nodup_iff_pairwise_ne.2 (List.Pairwise.filter _ (List.nodup_iff_pairwise_ne.1 hall))
  obtain ⟨hm, hp⟩ := foldr_insert_props g _ hf
  refine ⟨List.nodup_iff_pairwise_ne.2 (hp.imp fun h e => by subst e; exact before_irrefl g _ h),
    fun d => ?_, hp⟩
  unfold rank
  rw [hm d]
  simp [List.mem_filter, Dir.mem_all]

/-- T3b: Priority 1 dominates every non-empty cell (direct corollary of T3a). -/
theorem priority1_max (g : Grid) (d : Dir) (rest : List Dir) (h : rank g = d :: rest)
    (e : Dir) (he : (g e).total > 0) (hne : e ≠ d) : before g d e := by
  obtain ⟨_, hm, hp⟩ := rank_isRanking g
  have he' : e ∈ rank g := (hm e).2 he
  rw [h] at he' hp
  rcases List.mem_cons.1 he' with rfl | hrest
  · exact absurd rfl hne
  · exact (List.pairwise_cons.1 hp).1 e hrest

/-- T3c: rankings are unique — any list meeting the spec equals `rank g`.
    (Makes the checker's "recompute and compare" strategy complete, not just sound.) -/
theorem isRanking_unique (g : Grid) (r : List Dir) (h : IsRanking g r) : r = rank g := by
  obtain ⟨_, hm1, hp1⟩ := h
  obtain ⟨_, hm2, hp2⟩ := rank_isRanking g
  exact sorted_unique g r (rank g) hp1 hp2 (fun x => (hm1 x).trans (hm2 x).symm)

end CertBrief
