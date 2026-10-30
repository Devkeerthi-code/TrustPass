"""Parameter sweep: does any circuit parameter, decoy count or optimization level change a verdict?

One parameter at a time, the rest at the demo defaults (Grover 101; QAOA default graph, gamma 2.85,
beta 0.30; VQE reps 2, weight seed 11; decoys 0; optimization level 3):
  Grover  marked item 000-111
  QAOA    angles (gamma, beta) x 3, graph x 3   (qaoa_maxcut is one layer: no layer count to vary)
  VQE     reps 1-4, weight seed x 3             (lock() refuses odd reps: an odd CX count per pair)
  all     decoys 0-2, optimization level 1-3
Each setting x FakeBrisbane, FakeTorino: one fresh lock (OS entropy) shared by the 5 compilers, then
pipeline.run per compiler (transpiler seed 7, no noisy-sim evidence). The optimization level is the
compiler's: every level-3 transpile in compilers.py and score.py (honest, the attacks, the audit's
baseline, the plain-vs-locked overhead compiles) runs at the swept level instead.
Expected: honest ACCEPT, every attack REJECT; anything else is printed as an exception.
Settings run 4 at a time, one worker process each. A setting lock() refuses is recorded as LOCK REFUSED.
Writes bench/params.csv, bench/params_overhead.png and bench/params_esp.png.
    python bench/params.py            (~15 min; --chart redraws the PNGs from the CSV)
"""
import csv
import multiprocessing as mp
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import compilers  # noqa: E402
import score  # noqa: E402
from qiskit import transpile  # noqa: E402
from qiskit_ibm_runtime.fake_provider import FakeBrisbane, FakeTorino  # noqa: E402

from circuits import grover, qaoa_maxcut, vqe_ansatz  # noqa: E402
from lock import lock  # noqa: E402
from pipeline import run  # noqa: E402
from score import confidentiality  # noqa: E402
from verify import FIDELITY_RATIO  # noqa: E402

CSV, WORKERS = ROOT / "bench" / "params.csv", 4
PNG_OVERHEAD, PNG_ESP = ROOT / "bench" / "params_overhead.png", ROOT / "bench" / "params_esp.png"
FIELDS = ["circuit", "parameter", "value", "backend", "compiler", "key_angles", "visible_cx", "decoy_pairs",
          "2q_plain", "2q_locked", "depth_plain", "depth_locked", "ch1_tvd", "ch1_passed", "ch2_verdict",
          "ch3_esp_ratio", "ch3_verdict", "verdict", "expected", "indistinguishability"]

GRAPHS = {"default (5 edges)": ((0, 1), (1, 2), (2, 3), (3, 0), (0, 2)),
          "ring (4 edges)": ((0, 1), (1, 2), (2, 3), (3, 0)),
          "complete K4 (6 edges)": ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))}
DEFAULTS = {"Grover": grover, "QAOA": qaoa_maxcut, "VQE": vqe_ansatz}
# (circuit, parameter, value label, circuit factory, decoys, optimization level)
SETTINGS = (
    [("Grover", "marked item", m, lambda m=m: grover(m), 0, 3) for m in (format(i, "03b") for i in range(8))]
    + [("QAOA", "angles", f"g={g} b={b}", lambda g=g, b=b: qaoa_maxcut(gamma=g, beta=b), 0, 3)
       for g, b in ((2.85, 0.30), (0.8, 0.4), (1.9, 1.1))]
    + [("QAOA", "graph", name, lambda e=e: qaoa_maxcut(edges=e), 0, 3) for name, e in GRAPHS.items()]
    + [("VQE", "reps", str(r), lambda r=r: vqe_ansatz(reps=r), 0, 3) for r in (1, 2, 3, 4)]
    + [("VQE", "weight seed", str(s), lambda s=s: vqe_ansatz(seed=s), 0, 3) for s in (11, 1, 2)]
    + [(c, "decoys", str(d), f, d, 3) for c, f in DEFAULTS.items() for d in (0, 1, 2)]
    + [(c, "opt level", str(o), f, 0, o) for c, f in DEFAULTS.items() for o in (1, 2, 3)])


@contextmanager
def opt_level(level):
    """Run every optimization_level=3 transpile in compilers.py and score.py at `level` instead."""
    def at_level(*args, **kwargs):
        if kwargs.get("optimization_level") == 3:
            kwargs["optimization_level"] = level
        return transpile(*args, **kwargs)
    compilers.transpile = score.transpile = at_level
    try:
        yield
    finally:
        compilers.transpile = score.transpile = transpile


def setting(i):
    """All rows for SETTINGS[i]; settings are independent, so each runs in its own worker process."""
    name, param, value, make, decoys, level = SETTINGS[i]
    circuit, rows = make(), []
    for backend in (FakeBrisbane(), FakeTorino()):
        try:
            locked = lock(circuit, decoys=decoys)  # OS entropy; shared by the 5 compilers like the app
        except ValueError:  # odd CX gap on a pair: lock() refuses rather than leave the graph visible
            rows.append({"circuit": name, "parameter": param, "value": value, "backend": backend.name,
                         "verdict": "LOCK REFUSED", "expected": "ACCEPT/REJECT"})
            print(name, param, value, backend.name, "LOCK REFUSED", flush=True)
            continue
        conf = confidentiality(circuit, locked)
        with opt_level(level):
            for mode in compilers.COMPILERS:
                r = run(circuit, backend, mode, seed=7, evidence=False, locked=locked, conf=conf)
                o = r["overhead"]
                rows.append({
                    "circuit": name, "parameter": param, "value": value, "backend": backend.name,
                    "compiler": mode, "key_angles": conf["key_angles"], "visible_cx": conf["visible_2q_gates"],
                    "decoy_pairs": locked.decoys, "2q_plain": o["2q_plain"], "2q_locked": o["2q_locked"],
                    "depth_plain": o["depth_plain"], "depth_locked": o["depth_locked"],
                    "ch1_tvd": r["naive"]["tvd"], "ch1_passed": r["naive"]["passed"],
                    "ch2_verdict": r["functional"]["verdict"], "ch3_esp_ratio": r["fidelity"]["ratio"],
                    "ch3_verdict": r["fidelity"]["verdict"], "verdict": r["trust"]["verdict"],
                    "expected": "ACCEPT" if mode == "honest" else "REJECT",
                    "indistinguishability": conf["indistinguishability"]})
        print(name, param, value, backend.name, [x["verdict"] for x in rows[-5:]], flush=True)
    return rows


def sweep():
    with mp.Pool(WORKERS) as pool:
        return [row for rows in pool.map(setting, range(len(SETTINGS))) for row in rows]


PANELS = [("Grover", "marked item"), ("Grover", "decoys"), ("Grover", "opt level"),
          ("QAOA", "angles"), ("QAOA", "graph"), ("QAOA", "decoys"), ("QAOA", "opt level"),
          ("VQE", "reps"), ("VQE", "weight seed"), ("VQE", "decoys"), ("VQE", "opt level")]
SLOTS = {"Grover": [0, 2, 3], "QAOA": [4, 5, 6, 7], "VQE": [8, 9, 10, 11]}  # Grover has one circuit parameter


def chart(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    blue, orange = "#2a78d6", "#eb6834"
    ink, muted, surface, grid = "#0b0b0b", "#52514e", "#fcfcfb", "#e6e5e0"
    backends = {"fake_brisbane": ("FakeBrisbane", "o", "-"), "fake_torino": ("FakeTorino", "s", "--")}

    def grid_of(title, series, ylabel, path, threshold=None):
        fig, axes = plt.subplots(3, 4, figsize=(14, 8.5), facecolor=surface, sharey=bool(threshold))
        axes = axes.ravel()
        axes[1].axis("off")  # Grover has no second circuit parameter: the legend goes here
        slot = iter([s for c in ("Grover", "QAOA", "VQE") for s in SLOTS[c]])
        for circ, param in PANELS:
            ax = axes[next(slot)]
            sub = [r for r in rows if r["circuit"] == circ and r["parameter"] == param]
            values = list(dict.fromkeys(r["value"] for r in sub))
            for label, color, mode, key in series:
                for b, (bname, marker, ls) in backends.items():
                    y = [next((float(r[key]) if not callable(key) else key(r) for r in sub if r["value"] == v
                               and r["backend"] == b and r.get("compiler") == mode), float("nan")) for v in values]
                    ax.plot(range(len(values)), y, color=color, marker=marker, ms=7, lw=2, ls=ls,
                            label=f"{label}, {bname}" if label else bname)
            for x, v in enumerate(values):
                if all(r["verdict"] == "LOCK REFUSED" for r in sub if r["value"] == v):
                    ax.text(x, 0.2, "lock\nrefused", transform=ax.get_xaxis_transform(), ha="center",
                            va="center", fontsize=8, color=muted)
            if threshold:
                ax.axhline(threshold, color=muted, lw=1, ls=":")
                ax.text(len(values) - 1, threshold, f"{threshold:.2f}", color=muted, fontsize=8, va="bottom", ha="right")
            ax.set_xticks(range(len(values)))
            ax.set_xticklabels([v.split(" (")[0].replace(" b=", "\nb=") for v in values], fontsize=8, color=muted)
            ax.set_title(f"{circ}: {param}", color=ink, fontsize=10, loc="left")
            ax.set_facecolor(surface)
            ax.grid(axis="y", color=grid, lw=0.8)
            ax.tick_params(colors=muted, labelsize=8)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
        axes[1].legend(*axes[0].get_legend_handles_labels(), loc="center", frameon=False, fontsize=10)
        fig.suptitle(title, x=0.01, ha="left", color=ink, fontsize=12)
        fig.supylabel(ylabel, color=muted, fontsize=10)
        fig.tight_layout(rect=(0, 0, 1, 0.97))
        fig.savefig(path, dpi=110)
        plt.close(fig)

    ratio = lambda r: int(r["2q_locked"]) / int(r["2q_plain"])
    grid_of("Locking cost: compiled 2q gates, locked / plain (honest compile, transpiler seed 7)",
            [("", blue, "honest", ratio)], "locked / plain 2q gates", PNG_OVERHEAD)
    grid_of("Fidelity audit (CH3): ESP ratio to the honest baseline; below 0.90 is REJECT",
            [("honest", blue, "honest", "ch3_esp_ratio"), ("saboteur", orange, "saboteur", "ch3_esp_ratio")],
            "ESP ratio", PNG_ESP, threshold=FIDELITY_RATIO)


def summary(rows):
    refused = [r for r in rows if r["verdict"] == "LOCK REFUSED"]
    runs = [r for r in rows if r["verdict"] != "LOCK REFUSED"]
    bad = [r for r in runs if r["verdict"] != r["expected"]]
    print(f"\n{len(runs)} runs, {len(runs) - len(bad)} verdicts as expected, {len(bad)} exceptions")
    for r in refused:
        print(f"  lock refused: {r['circuit']} {r['parameter']}={r['value']} {r['backend']}")
    for r in bad:
        print(f"  {r['circuit']} {r['parameter']}={r['value']} {r['backend']} {r['compiler']}: {r['verdict']} "
              f"(CH2 {r['ch2_verdict']}, CH3 ratio {r['ch3_esp_ratio']})")


def main():
    if "--chart" in sys.argv:
        rows = list(csv.DictReader(CSV.open()))
    else:
        rows = sweep()
        with CSV.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
    chart(rows)
    summary(rows)


if __name__ == "__main__":
    main()
