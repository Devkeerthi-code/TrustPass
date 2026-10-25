"""95% bootstrap intervals for the hardware results: how much of each difference is shot noise?

For every circuit in the completed ibm_fez and ibm_kingston bench JSON files, resample its measured
counts 1,000 times (multinomial, same shot count) and recompute 1-TVD against the same ideal
reference; the measured ratio resamples the circuit and its honest compile independently (the
honest row divides one draw by itself, so its ratio stays 1). Intervals are the 2.5th-97.5th
percentiles. A difference from the honest compile is significant when the ratio interval excludes 1.
The ideal reference is held fixed (exact for runs 2-3, a 4,000-shot sample for run 1). bench/compare.py
adds these intervals to bench/hardware.csv and the README table.
    python bench/confidence.py
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RESAMPLES, SEED = 1000, 0  # the seed only makes the bootstrap reproducible; nothing here is a lock


def circuits(d):
    """(circuit, mode, counts, ideal) per circuit of one job file, in the order compare.load reads them."""
    if "runs" in d:  # demo.py --ibm
        return [(d["circuit"], m, r["counts"], d["ideal_counts"]) for m, r in d["runs"].items()]
    return [(e["circuit"], e["mode"], e["counts"], e["ideal"]) for e in d["circuits"]]


def _fidelity_draws(counts, ideal, rng):
    keys = sorted(set(counts) | set(ideal))
    shots = sum(counts.values())
    p = np.array([counts.get(k, 0) for k in keys]) / shots
    q = np.array([ideal.get(k, 0) for k in keys], dtype=float)
    draws = rng.multinomial(shots, p, size=RESAMPLES) / shots
    return 1 - 0.5 * np.abs(draws - q / q.sum()).sum(axis=1)


def intervals(d):
    """[(lo, hi, ratio_lo, ratio_hi)] aligned with circuits(d)."""
    rng = np.random.default_rng(SEED)
    items = circuits(d)
    draws = [_fidelity_draws(c, i, rng) for _, _, c, i in items]
    honest = {name: draws[k] for k, (name, mode, _, _) in enumerate(items) if mode == "honest"}
    pct = lambda x: [round(float(v), 4) for v in np.percentile(x, (2.5, 97.5))]
    return [(*pct(f), *pct(f / honest[name])) for f, (name, _, _, _) in zip(draws, items)]


def files():
    for path in sorted((ROOT / "bench").glob("ibm_*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        if d["device"] in ("ibm_fez", "ibm_kingston") and ("runs" in d or all("counts" in e for e in d["circuits"])):
            yield d


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    for d in files():
        for (name, mode, _, _), (lo, hi, rlo, rhi) in zip(circuits(d), intervals(d)):
            sig = "" if mode == "honest" else ("  significant" if rhi < 1 or rlo > 1 else "  not significant")
            print(f"{d['job_id']} {d['device']:<13}{name.split(' ')[0]:<7}{mode:<16}"
                  f"1-TVD [{lo:.3f}, {hi:.3f}]  ratio [{rlo:.3f}, {rhi:.3f}]{sig}")


if __name__ == "__main__":
    main()
