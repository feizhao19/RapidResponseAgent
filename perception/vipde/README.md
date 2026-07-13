# ViPDE package (proprietary)

This directory holds the **closed-source** ViPDE Python package used for
damage perception. Model source under `models/` and `utils/` is **not**
tracked by git and must not be committed.

## Local install

Place the licensed ViPDE package here so imports like `from vipde.models import ViPDE` work:

```
perception/vipde/
  __init__.py
  models/          # ViPDE class, blocks (local only)
  utils/           # preprocess, device, TTA, viz (local only)
```

Weights go in `perception/checkpoints/` (also gitignored). See
`perception/README.md` for setup and access requests.
