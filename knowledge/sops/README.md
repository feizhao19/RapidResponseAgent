# Public emergency guidance corpus

Markdown guides curated from **public U.S. government / Cal OES** sources.
Each file lists `source_url` in the YAML front matter for citation.

Current seed set covers:

- FEMA: FMAG, wildfire PA/PPDR, declarations, PDA Guide/Pocket Guide, IA housing damage levels, NIMS/ICS, lifelines/critical facilities, JIS messaging
- USFA/FEMA: wildfire evacuation planning
- NWS: Red Flag / Fire Weather Watch basics
- Cal OES: fire/rescue mutual aid, pre-incident mobilization, SEMS OA EOC Fire & Rescue
- Ready.gov: wildfire preparedness / evacuation basics, impact mitigation & protective actions

Rebuild the Chroma index after adding files:

```bash
PYTHONPATH=. python scripts/build_knowledge_rag_index.py
```

Do **not** add non-public / internal SOPs here without explicit license approval.
