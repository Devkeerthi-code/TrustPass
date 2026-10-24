"""Threshold sweep: where do the fidelity audit's 0.90 and the naive test's 0.10 sit?

For each demo x backend, 5 fresh locks. Per lock, against the pipeline's baseline (level 3, seed 7):
  honest   optimization levels 1-3 x transpiler seeds 0-4   (what a fair compiler might return)
  saboteur transpiler seeds 0-4                             (equivalent, parked on bad qubits)
  masked   transpiler seeds 0-4                             (rz(0.35) Trojan, the naive test's target)
Writes bench/thresholds.csv (one row per compile) and bench/thresholds.png, and prints the sweeps.
    python bench/thresholds.py        (~15 min)
"""
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qiskit import transpile  # noqa: E402
from qiskit_ibm_runtime.fake_provider import FakeBrisbane, FakeTorino  # noqa: E402

from circuits import DEMOS  # noqa: E402
from compilers import honest, saboteur, trojan_masked  # noqa: E402
from lock import lock, unlock  # noqa: E402
from verify import FIDELITY_RATIO, NAIVE_TOL, counts, esp, tvd  # noqa: E402

LOCKS, SEEDS, LEVELS = 5, range(5), (1, 2, 3)
ESP_SWEEP = np.round(np.arange(0.50, 1.0001, 0.01), 2)
TVD_SWEEP = np.round(np.arange(0.00, 0.2001, 0.005), 3)
CSV, PNG = ROOT / "bench" / "thresholds.csv", ROOT / "bench" / "thresholds.png"


def collect():
    rows = []
    for demo, make in DEMOS.items():
        circuit = make()
        ideal = counts(circuit)
        for backend in (FakeBrisbane(), FakeTorino()):
            for k in range(LOCKS):
                locked = lock(circuit)  # fresh OS entropy every time, as in the pipeline
                base = esp(unlock(honest(locked.circuit, backend, seed=7), locked.key), backend.target)
                compiles = [("honest", lvl, s, transpile(locked.circuit, backend, optimization_level=lvl,
                                                         seed_transpiler=s)) for lvl in LEVELS for s in SEEDS]
                compiles += [("saboteur", 3, s, saboteur(locked.circuit, backend, seed=s)) for s in SEEDS]
                compiles += [("masked", 3, s, trojan_masked(locked.circuit, backend, seed=s)) for s in SEEDS]
                for kind, lvl, s, c in compiles:
                    final = unlock(c, locked.key)
                    rows.append({"demo": demo.split(" (")[0], "backend": backend.name, "lock": k, "kind": kind,
                                 "opt_level": lvl, "seed": s,
                                 "esp_ratio": round(esp(final, backend.target) / base, 4),
                                 "naive_tvd": round(tvd(ideal, counts(final)), 4)})
            print(f"{demo} / {backend.name}: done", flush=True)
    return rows


def sweep(rows):
    col = lambda kind, key: np.array([r[key] for r in rows if r["kind"] == kind])
    h_esp, sab, h_tvd, mask = col("honest", "esp_ratio"), col("saboteur", "esp_ratio"), \
        col("honest", "naive_tvd"), col("masked", "naive_tvd")
    esp_fr = [(h_esp < t).mean() for t in ESP_SWEEP]   # audit rejects when ratio < threshold
    esp_miss = [(sab >= t).mean() for t in ESP_SWEEP]
    tvd_fr = [(h_tvd >= t).mean() for t in TVD_SWEEP]  # naive test passes when TVD < tolerance
    tvd_miss = [(mask < t).mean() for t in TVD_SWEEP]
    print(f"honest ESP ratio {h_esp.min():.3f}-{h_esp.max():.3f} (n={len(h_esp)}), "
          f"saboteur {sab.min():.3f}-{sab.max():.3f} (n={len(sab)})")
    ok = [t for t, a, b in zip(ESP_SWEEP, esp_fr, esp_miss) if a == 0 and b == 0]
    print(f"ESP thresholds with 0 false rejects and 0 missed saboteurs: "
          f"{f'{min(ok):.2f}-{max(ok):.2f}' if ok else 'none'}")
    i = int(np.argmin(abs(ESP_SWEEP - FIDELITY_RATIO)))
    print(f"at {FIDELITY_RATIO}: false rejects {esp_fr[i]:.3f}, missed saboteurs {esp_miss[i]:.3f}")
    print(f"honest naive TVD {h_tvd.min():.4f}-{h_tvd.max():.4f}, masked {mask.min():.4f}-{mask.max():.4f} (n={len(mask)})")
    j = int(np.argmin(abs(TVD_SWEEP - NAIVE_TOL)))
    print(f"at {NAIVE_TOL}: false rejects {tvd_fr[j]:.3f}, missed masked Trojans {tvd_miss[j]:.3f}")
    best = min(range(len(TVD_SWEEP)), key=lambda x: tvd_fr[x] + tvd_miss[x])
    print(f"best tolerance {TVD_SWEEP[best]:.3f}: false rejects {tvd_fr[best]:.3f}, missed {tvd_miss[best]:.3f}")
    return esp_fr, esp_miss, tvd_fr, tvd_miss


def chart(esp_fr, esp_miss, tvd_fr, tvd_miss):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    blue, orange, ink, muted = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e"
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), facecolor="#fcfcfb")
    panels = [(axes[0], ESP_SWEEP, esp_fr, esp_miss, FIDELITY_RATIO, "Fidelity audit: ESP ratio threshold",
               "missed saboteurs"),
              (axes[1], TVD_SWEEP, tvd_fr, tvd_miss, NAIVE_TOL, "Naive |0> test: TVD tolerance",
               "missed masked Trojans")]
    for ax, x, fr, miss, chosen, title, miss_label in panels:
        ax.set_facecolor("#fcfcfb")
        ax.plot(x, fr, color=blue, lw=2, label="false rejects (honest compiles)")
        ax.plot(x, miss, color=orange, lw=2, label=miss_label)
        ax.axvline(chosen, color=muted, lw=1, ls="--")
        ax.text(chosen, 1.04, f"TrustPass: {chosen:.2f}", color=muted, ha="center", fontsize=9)
        ax.set_title(title, color=ink, fontsize=11, loc="left", pad=18)
        ax.set_ylim(-0.02, 1.0)
        ax.set_ylabel("share of compiles", color=muted)
        ax.grid(axis="y", color="#e6e5e0", lw=0.8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=muted)
        ax.legend(frameon=False, fontsize=9, loc="center right")
    fig.tight_layout()
    fig.savefig(PNG, dpi=120)


def main():
    rows = collect()
    with CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    chart(*sweep(rows))


if __name__ == "__main__":
    main()
