import CertBrief
import Lean.Data.Json

/-!
# `certbrief` — JSON bridge to the verified checker

stdin:  one request object, or an array of request objects (batch).
stdout: one response object, or an array of responses (same order).

Request
```json
{ "facts":  { "aoi":  {"no_damage": 450, "minor": 10, "major": 29, "destroyed": 287},
              "grid": {"NE": {"no_damage": 12, "minor": 1, "major": 3, "destroyed": 20}} },
  "claims": [ {"kind": "count", "scope": "NE", "level": "destroyed", "n": 20},
              {"kind": "pct", "scope": "aoi", "level": "destroyed", "mantissa": 3698, "decimals": 2},
              {"kind": "priority", "n": 1, "direction": "NE"},
              {"kind": "action", "scope": "NE", "action": "Immediate Search & Rescue"} ],
  "turn":   { "active_aoi": 0, "gated": ["get_mission_priority"], "confirmed": false,
              "executed": [{"tool": "get_mission_priority", "aoi": 0}],
              "sources":  [{"tool": "get_mission_priority", "aoi": 0}] } }
```
(`turn` is optional.) Response: `{"verdicts": [true, …], "grid_consistent": true, "policy": true | null}`

This file only *decodes* JSON. Every verdict comes from the proved definitions
`CertBrief.check` (T5), `CertBrief.checkPolicy` (T6) and `CertBrief.gridConsistent`.
Missing grid cells are zero. AOI ids are interned to Nat by the caller.
-/

open Lean (Json)
open CertBrief

namespace Bridge

abbrev M := Except String

def natAt (j : Json) (k : String) : M Nat := do (← j.getObjVal? k).getNat?
def strAt (j : Json) (k : String) : M String := do (← j.getObjVal? k).getStr?

def dirName : Dir → String
  | .NW => "NW" | .N => "N" | .NE => "NE" | .W => "W" | .Center => "Center"
  | .E => "E" | .SW => "SW" | .S => "S" | .SE => "SE"

def parseDir (s : String) : M Dir :=
  match Dir.all.find? (dirName · == s) with
  | some d => pure d
  | none => throw s!"unknown direction {s}"

def parseLevel : String → M Level
  | "no_damage" => pure .noDamage
  | "minor" => pure .minor
  | "major" => pure .major
  | "destroyed" => pure .destroyed
  | s => throw s!"unknown level {s}"

def parseAction : String → M Action
  | "Rapid inspection" => pure .rapidInspection
  | "Fire suppression / hazard control" => pure .fireSuppression
  | "Immediate Search & Rescue" => pure .searchRescue
  | s => throw s!"unknown action {s}"

def parseTool : String → M Tool
  | "get_damage_stats" => pure .damageStats
  | "get_mission_priority" => pure .missionPriority
  | "find_nearest_hospitals" => pure .hospitals
  | "find_nearest_facilities" => pure .facilities
  | "weather_context" => pure .weather
  | "situation_roads" => pure .roads
  | "query_historical" => pure .historical
  | "generate_report" => pure .report
  | "query_guidance" => pure .guidance
  | s => throw s!"unknown tool {s}"

def parseCounts (j : Json) : M Counts :=
  return ⟨← natAt j "no_damage", ← natAt j "minor", ← natAt j "major", ← natAt j "destroyed"⟩

def parseGrid (j : Json) : M Grid := do
  let cells ← Dir.all.mapM fun d => do
    match j.getObjVal? (dirName d) with
    | .ok c => return (d, ← parseCounts c)
    | .error _ => return (d, Counts.zero)
  return fun d => ((cells.find? (·.1 == d)).map (·.2)).getD Counts.zero

def parseFacts (j : Json) : M Facts := do
  return { aoi := ← parseCounts (← j.getObjVal? "aoi"), grid := ← parseGrid (← j.getObjVal? "grid") }

def scopeOf (j : Json) : M Scope :=
  match j.getObjVal? "scope" with
  | .ok s => do
    let name ← s.getStr?
    if name == "aoi" then pure .aoi else return .cell (← parseDir name)
  | .error _ => pure .aoi

def parseClaim (j : Json) : M Claim := do
  match ← strAt j "kind" with
  | "count"    => return .count (← scopeOf j) (← parseLevel (← strAt j "level")) (← natAt j "n")
  | "total"    => return .total (← scopeOf j) (← natAt j "n")
  | "damaged"  => return .damaged (← scopeOf j) (← natAt j "n")
  | "impact"   => return .impact (← scopeOf j) (← natAt j "n")
  | "pct"      => return .pct (← scopeOf j) (← parseLevel (← strAt j "level"))
                    (← natAt j "mantissa") (← natAt j "decimals")
  | "priority" => return .priority (← natAt j "n") (← parseDir (← strAt j "direction"))
  | "action"   =>
      match ← scopeOf j with
      | .cell d => return .action d (← parseAction (← strAt j "action"))
      | .aoi => throw "action claim needs a cell scope"
  | k => throw s!"unknown claim kind {k}"

def optAoi (j : Json) (k : String) : M (Option Nat) :=
  match j.getObjVal? k with
  | .ok .null => pure none
  | .ok v => return some (← v.getNat?)
  | .error _ => pure none

def parseCall (j : Json) : M Call := do
  return ⟨← parseTool (← strAt j "tool"), ← optAoi j "aoi"⟩

def parseSource (j : Json) : M Source := do
  return ⟨← parseTool (← strAt j "tool"), ← optAoi j "aoi"⟩

def arrAt (j : Json) (k : String) : M (List Json) := do
  return (← (← j.getObjVal? k).getArr?).toList

def parseTurn (j : Json) : M Turn := do
  let gated ← (← arrAt j "gated").mapM fun t => do parseTool (← t.getStr?)
  let executed ← (← arrAt j "executed").mapM parseCall
  let sources ← (← arrAt j "sources").mapM parseSource
  let confirmed ← (← j.getObjVal? "confirmed").getBool?
  return { activeAoi := ← optAoi j "active_aoi", gated, confirmed, executed, sources }

def processOne (j : Json) : M Json := do
  let facts ← parseFacts (← j.getObjVal? "facts")
  let claims ← (← arrAt j "claims").mapM parseClaim
  let policy ← match j.getObjVal? "turn" with
    | .ok .null => pure Json.null
    | .ok t => do pure (Json.bool (checkPolicy (← parseTurn t)))  -- `pure`, not `return` (early exit)
    | .error _ => pure Json.null
  return Json.mkObj [
    ("verdicts", Json.arr (claims.map (fun c => Json.bool (check facts c))).toArray),
    ("grid_consistent", Json.bool (gridConsistent facts)),
    ("policy", policy)]

partial def readAll (s : IO.FS.Stream) (acc : String) : IO String := do
  let line ← s.getLine
  if line.isEmpty then return acc else readAll s (acc ++ line)

end Bridge

def main : IO UInt32 := do
  let input ← Bridge.readAll (← IO.getStdin) ""
  match Json.parse input with
  | .error e =>
    IO.eprintln s!"certbrief: invalid JSON: {e}"
    return 2
  | .ok j =>
    let out : Except String Json := match j with
      | .arr reqs => do return Json.arr (← reqs.mapM Bridge.processOne)
      | other => Bridge.processOne other
    match out with
    | .ok r =>
      IO.println r.compress
      return 0
    | .error e =>
      IO.eprintln s!"certbrief: {e}"
      return 1
