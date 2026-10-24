# TrustPass

Zero-trust compilation for quantum circuits: lock the circuit (keyed rotations + decoys) before an
untrusted compiler sees it, unlock what comes back, then check it is the same circuit (MQT QCEC
equivalence) and does not run measurably worse than a free local compile (fidelity audit on IBM fake
backends). Q-HACK INDIA 2026 entry, Quantum Security & Cryptography track.

- Repo: Devkeerthi-code/TrustPass (remote name `copy`). Default branch `main`.
- Site: `index.html` + `web/` (+ `assets/`), served by GitHub Pages from `main`. On Pages the UI reads
  `web/snapshot.json`; regenerate it with `python server.py --export` after any pipeline change.
- Live UI: `python server.py` -> http://localhost:8600 (JSON API under `/api/`).
- Pipeline: `lock.py` -> `compilers.py` -> `verify.py` -> `score.py`, wired in `pipeline.py`.
  Demos in `circuits.py`, CLI in `demo.py` (`--matrix` for the detection matrix).

## Environment
- Python 3.12 in `.venv` (`py -3.12 -m venv .venv`, then `pip install -r requirements.txt`).
  Never commit `.venv`.
- Run `python test_trustpass.py` before every commit; it must end with 0 failed.

## Rules
- Never invent numbers. Every figure in README, docs or UI must come from a real pipeline run;
  keep the README's honest, hedged tone.
- UI changes follow DESIGN.md (bench-instrument style) and PRODUCT.md.
- The lock is never seeded (OS entropy only); `seed` fixes only the transpiler.
- Small, focused edits; don't refactor unrelated code.
- "AI slop" submissions are rejected: every change must be one the team can explain line by line.

## Judging weights
Technical 30 · Quantum Relevance 20 · Originality 20 · Problem 10 · Impact 10 · Presentation 10.
