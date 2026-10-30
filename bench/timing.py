"""Timing: how long each pipeline step takes, per circuit x backend x decoys x compiler.

Every combination of the 3 demos x FakeBrisbane, FakeTorino x decoys 0-2 x the 5 compilers runs
3 times, each repeat with a fresh lock (OS entropy) and transpiler seed 7. Steps, timed separately:
  lock      lock(circuit, decoys)
  compile   the compiler under test on the locked circuit
  unlock    binding the key
  naive     naive_check (two 8192-shot ideal simulations + TVD)
  qcec      check_function (output map + QCEC)
  audit     the audit's baseline (honest compile of the same lock, unlocked) + audit_fidelity
  scoring   confidentiality + overhead (plain and locked compiles) + trust
  total     the sum of the 7 steps
Plus one full detection matrix (pipeline.detection_matrix: lock + 5 compilers, no scoring) per
demo x backend, also 3 times. One untimed warm-up run per backend first. Run nothing else while it
measures. Writes bench/timing.csv (median, min, max seconds; machine in the header) and bench/timing.png.
    python bench/timing.py            (~10 min; --chart redraws the PNG from the CSV)
"""
import csv
import os
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qiskit_ibm_runtime.fake_provider import FakeBrisbane, FakeTorino  # noqa: E402

from circuits import DEMOS  # noqa: E402
from compilers import COMPILERS, honest  # noqa: E402
from lock import lock, unlock  # noqa: E402
from pipeline import detection_matrix  # noqa: E402
from score import confidentiality, overhead, trust  # noqa: E402
from verify import audit_fidelity, check_function, naive_check  # noqa: E402

REPEATS, DECOYS, SEED = 3, (0, 1, 2), 7
STEPS = ["lock", "compile", "unlock", "naive", "qcec", "audit", "scoring"]
SHORT = {"Grover search (marked item)": "Grover", "QAOA MaxCut (graph + angles)": "QAOA",
         "VQE ansatz (trained weights)": "VQE"}
CSV, PNG = ROOT / "bench" / "timing.csv", ROOT / "bench" / "timing.png"
FIELDS = ["kind", "circuit", "backend", "decoys", "compiler"] + [
    f"{s}_{stat}" for s in STEPS + ["total"] for stat in ("median", "min", "max")]


def machine():
    cpu = platform.processor()
    try:  # Windows keeps the marketing name in the registry; platform.processor() is only the family
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            cpu = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
    except (ImportError, OSError):
        pass
    import qiskit
    from mqt import qcec
    return (f"{cpu}, {os.cpu_count()} logical cores; {platform.platform()}; Python {platform.python_version()}; "
            f"qiskit {qiskit.__version__}, mqt.qcec {qcec.__version__}")


def one_run(circuit, backend, decoys, mode):
    """The pipeline's steps in order, each under its own clock."""
    t = {}

    def step(key, fn):
        start = time.perf_counter()
        out = fn()
        t[key] = time.perf_counter() - start
        return out

    locked = step("lock", lambda: lock(circuit, decoys=decoys))
    compiled = step("compile", lambda: COMPILERS[mode](locked.circuit, backend, seed=SEED))
    final = step("unlock", lambda: unlock(compiled, locked.key))
    step("naive", lambda: naive_check(circuit, final))
    functional = step("qcec", lambda: check_function(circuit, final))
    fidelity = step("audit", lambda: audit_fidelity(
        final, backend, unlock(honest(locked.circuit, backend, seed=SEED), locked.key)))
    step("scoring", lambda: (overhead(circuit, locked, backend, seed=SEED),
                             trust(functional, fidelity, confidentiality(circuit, locked))))
    t["total"] = sum(t[k] for k in STEPS)
    return t


def stats(samples, key):
    xs = [x[key] for x in samples]
    return {f"{key}_median": round(statistics.median(xs), 4), f"{key}_min": round(min(xs), 4),
            f"{key}_max": round(max(xs), 4)}


def measure():
    rows, backends = [], (FakeBrisbane(), FakeTorino())
    for backend in backends:  # warm-up: imports, simulator and target caches
        one_run(next(iter(DEMOS.values()))(), backend, 0, "honest")
    for name, make in DEMOS.items():
        circuit = make()
        for backend in backends:
            for decoys in DECOYS:
                for mode in COMPILERS:
                    samples = [one_run(circuit, backend, decoys, mode) for _ in range(REPEATS)]
                    row = {"kind": "steps", "circuit": SHORT[name], "backend": backend.name, "decoys": decoys,
                           "compiler": mode}
                    for key in STEPS + ["total"]:
                        row.update(stats(samples, key))
                    rows.append(row)
                    print(SHORT[name], backend.name, decoys, mode, row["total_median"], flush=True)
            samples = []
            for _ in range(REPEATS):
                s = time.perf_counter()
                detection_matrix(circuit, backend)
                samples.append({"total": time.perf_counter() - s})
            rows.append({"kind": "matrix", "circuit": SHORT[name], "backend": backend.name, "decoys": 0,
                         "compiler": "all 5", **stats(samples, "total")})
            print(SHORT[name], backend.name, "matrix", rows[-1]["total_median"], flush=True)
    return rows


def chart(rows):
    """Per circuit: the six steps up to the verdict stacked on one scale, scoring beside them on its own."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
    ink, muted, surface, grid = "#0b0b0b", "#52514e", "#fcfcfb", "#e6e5e0"
    abbrev = {"honest": "H", "trojan-overt": "O", "trojan-masked": "M", "trojan-dormant": "D", "saboteur": "S"}
    steps = [r for r in rows if r["kind"] == "steps"]
    verdict_steps = STEPS[:-1]
    fig, axes = plt.subplots(3, 2, figsize=(14, 10), facecolor=surface, sharey="col",
                             gridspec_kw={"width_ratios": (3, 2)})
    for (left, right), circ in zip(axes, ("Grover", "QAOA", "VQE")):
        sub = [r for r in steps if r["circuit"] == circ]
        x = [i + 1.2 * (i // 5) for i in range(len(sub))]  # a gap after every 5 compilers (backend x decoys)
        bottom = [0.0] * len(sub)
        for step, c in zip(verdict_steps, colors):
            h = [float(r[f"{step}_median"]) for r in sub]
            left.bar(x, h, bottom=bottom, width=0.8, color=c, edgecolor=surface, linewidth=1, label=step)
            bottom = [b + v for b, v in zip(bottom, h)]
        right.bar(x, [float(r["scoring_median"]) for r in sub], width=0.8, color=colors[6], label="scoring")
        matrix = [r for r in rows if r["kind"] == "matrix" and r["circuit"] == circ]
        note = "; ".join(f"{'Brisbane' if m['backend'] == 'fake_brisbane' else 'Torino'} "
                         f"{float(m['total_median']):.1f} s" for m in matrix)
        left.set_title(f"{circ}: lock to verdict   (one detection matrix, median: {note})", color=ink,
                       fontsize=10, loc="left")
        right.set_title(f"{circ}: scoring (confidentiality + overhead)", color=ink, fontsize=10, loc="left")
        for ax in (left, right):
            ax.set_xticks(x)
            ax.set_xticklabels([abbrev[r["compiler"]] for r in sub], fontsize=7, color=muted)
            for g in range(0, len(sub), 5):
                r = sub[g]
                name = "Bris." if r["backend"] == "fake_brisbane" else "Torino"
                ax.text((x[g] + x[g + 4]) / 2, -0.14, f"{name} d={r['decoys']}", transform=ax.get_xaxis_transform(),
                        ha="center", va="top", fontsize=8, color=ink)
            ax.set_ylabel("seconds", color=muted)
            ax.set_facecolor(surface)
            ax.grid(axis="y", color=grid, lw=0.8)
            ax.set_axisbelow(True)
            ax.tick_params(colors=muted)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
    handles = [h for ax in axes[0] for h in ax.get_legend_handles_labels()[0]]
    fig.legend(handles, verdict_steps + ["scoring"], ncol=7, frameon=False, fontsize=9, loc="upper left",
               bbox_to_anchor=(0.01, 0.965))
    fig.suptitle("Median seconds per pipeline step, 3 repeats per bar "
                 "(H honest, O trojan-overt, M trojan-masked, D trojan-dormant, S saboteur; d = decoys)",
                 x=0.01, ha="left", color=ink, fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.94), h_pad=2.5)
    fig.savefig(PNG, dpi=110)
    plt.close(fig)


def main():
    if "--chart" in sys.argv:
        rows = list(csv.DictReader(line for line in CSV.open() if not line.startswith("#")))
    else:
        rows = measure()
        with CSV.open("w", newline="") as f:
            f.write(f"# machine: {machine()}\n# seconds; {REPEATS} repeats per row, fresh lock each repeat\n")
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
    chart(rows)


if __name__ == "__main__":
    main()
