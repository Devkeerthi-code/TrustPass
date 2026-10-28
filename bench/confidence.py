"""95% bootstrap intervals for the hardware results: how much of each difference is shot noise?

For every circuit in the completed bench JSON files (bench/ibm_*.json and the
panel's bench/live_ibm/*.json), resample its measured
counts 1,000 times (multinomial, same shot count) and recompute 1-TVD against the same ideal
reference; the measured ratio resamples the circuit and its honest compile independently (the
honest row divides one draw by itself, so its ratio stays 1). Intervals are the 2.5th-97.5th
percentiles. A difference from the honest compile is significant when the ratio interval excludes 1.
The ideal reference is held fixed (exact for every run but run 1, a 4,000-shot sample there). bench/compare.py
adds these intervals to bench/hardware.csv and the README table.
    python bench/confidence.py
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from circuits import DEMOS

RESAMPLES, SEED = 1000, 0  # the seed only makes the bootstrap reproducible; nothing here is a lock


def circuits(d):
    """(circuit, mode, counts, ideal) per circuit of one job file, in the order compare.load reads them."""
    if "runs" in d:  # demo.py --ibm
        return [(d["circuit"], m, r["counts"], d["ideal_counts"]) for m, r in d["runs"].items()]
    if "results" in d:  # server.py --allow-ibm panel job: the judge's compile, then its honest baseline
        name = dict(zip(("grover", "qaoa", "vqe"), DEMOS))[d["params"]["circuit"]]
        return [(name, mode, d["results"][k]["counts"], d["ideal"])
                for k, mode in (("judge", d["params"]["mode"]), ("baseline", "honest"))]
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


def done(d):
    """True once a job file holds its measured counts (queued jobs are skipped)."""
    return "runs" in d or "results" in d or all(isinstance(e, dict) and "counts" in e for e in d["circuits"])


def jobs():
    """Every hardware job file: bench/ibm_*.json, then the panel's bench/live_ibm/*.json."""
    bench = ROOT / "bench"
    for path in sorted(bench.glob("ibm_*.json")) + sorted((bench / "live_ibm").glob("*.json")):
        yield json.loads(path.read_text(encoding="utf-8"))


def files():
    for d in jobs():
        if done(d):
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
