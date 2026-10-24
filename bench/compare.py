"""Predicted vs measured: every real IBM hardware run in bench/, in one chart and one table.

Reads bench/ibm_*.json (run 1 from `demo.py --ibm`, the rest from bench/ibm_runs.py; jobs still
queued are skipped). Measured ratio = measured 1-TVD / the honest compile's measured 1-TVD for the
same lock on the same device, the hardware counterpart of the ESP ratio. Run 1 recorded no noisy-sim
prediction, and its 1-TVD is against a 4,000-shot ideal sample instead of the exact distribution.
Writes bench/hardware.csv, bench/compare.png and web/hardware.json, and prints the README table.
    python bench/compare.py
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from verify import NAIVE_TOL

CSV, PNG, WEB = ROOT / "bench" / "hardware.csv", ROOT / "bench" / "compare.png", ROOT / "web" / "hardware.json"
FIELDS = ["run", "device", "job_id", "submitted_utc", "circuit", "mode", "verdict", "esp_ratio",
          "predicted_one_minus_tvd", "measured_one_minus_tvd", "measured_ratio", "naive_hw_passed"]
MODES = ("honest", "trojan-overt", "trojan-masked", "trojan-dormant", "saboteur")
COLORS = dict(zip(MODES, ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4")))
MARKERS = dict(zip(MODES, ("o", "s", "^", "v", "D")))


def load():
    rows = []
    for path in sorted((ROOT / "bench").glob("ibm_*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        if "runs" in d:  # demo.py --ibm: honest + saboteur, one circuit
            honest = d["runs"]["honest"]["one_minus_tvd"]
            for mode, r in d["runs"].items():
                rows.append({"device": d["device"], "job_id": d["job_id"], "submitted_utc": d["submitted_utc"],
                             "circuit": d["circuit"], "mode": mode, "verdict": r["verdict"],
                             "esp_ratio": r["esp_ratio"], "predicted_one_minus_tvd": None,
                             "measured_one_minus_tvd": r["one_minus_tvd"],
                             "measured_ratio": round(r["one_minus_tvd"] / honest, 3),
                             "naive_hw_passed": 1 - r["one_minus_tvd"] < NAIVE_TOL})
        elif all("counts" in e for e in d["circuits"]):
            rows += [{"device": d["device"], "job_id": d["job_id"], "submitted_utc": d["submitted_utc"],
                      **{k: e[k] for k in FIELDS[4:]}} for e in d["circuits"]]
    jobs = sorted({(r["submitted_utc"], r["job_id"]) for r in rows})
    for r in rows:
        r["run"] = jobs.index((r["submitted_utc"], r["job_id"])) + 1
        r["circuit"] = r["circuit"].split(" ")[0]
    order = {m: i for i, m in enumerate(MODES)}
    return sorted(rows, key=lambda r: (r["run"], r["circuit"], order[r["mode"]]))


def chart(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, muted, surface = "#0b0b0b", "#52514e", "#fcfcfb"
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 5), facecolor=surface)
    panels = ((a, "esp_ratio", "measured_ratio", "ESP ratio (audit, before running)",
               "measured fidelity ratio (1-TVD / honest)", "Audit prediction vs hardware"),
              (b, "predicted_one_minus_tvd", "measured_one_minus_tvd", "predicted 1-TVD (noisy simulator)",
               "measured 1-TVD", "Noisy-simulator prediction vs hardware"))
    for ax, x, y, xl, yl, title in panels:
        ax.plot([0, 1.05], [0, 1.05], color=muted, lw=1, ls="--", zorder=1)
        ax.text(0.52, 0.47, "y = x", color=muted, fontsize=8, rotation=45, ha="left", va="top")
        for mode in MODES:
            pts = [(r[x], r[y]) for r in rows if r["mode"] == mode and r[x] is not None]
            if pts:
                ax.scatter(*zip(*pts), s=46, color=COLORS[mode], marker=MARKERS[mode], label=mode,
                           edgecolors=surface, linewidths=1.5, zorder=3)
        ax.set_xlim(0, 1.05)
        ax.set_ylim(0, 1.05)
        ax.set_facecolor(surface)
        ax.set_xlabel(xl, color=muted)
        ax.set_ylabel(yl, color=muted)
        ax.set_title(title, color=ink, fontsize=11, loc="left")
        ax.grid(color="#e6e5e0", lw=0.8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=muted)
    fig.legend(*a.get_legend_handles_labels(), frameon=False, fontsize=9, loc="lower center", ncol=len(MODES))
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(PNG, dpi=120)


def web(rows):
    """Honest vs saboteur, per device and circuit, for the site's hardware block."""
    out = []
    for r in rows:
        if r["mode"] != "saboteur":
            continue
        h = next(x for x in rows if x["run"] == r["run"] and x["circuit"] == r["circuit"] and x["mode"] == "honest")
        out.append({"run": r["run"], "device": r["device"], "date": r["submitted_utc"][:10], "job_id": r["job_id"],
                    "circuit": r["circuit"], "honest": {"verdict": h["verdict"], "measured": h["measured_one_minus_tvd"]},
                    "saboteur": {"verdict": r["verdict"], "measured": r["measured_one_minus_tvd"],
                                 "esp_ratio": r["esp_ratio"]}})
    WEB.write_text(json.dumps({"metric": "measured 1-TVD vs ideal", "runs": out}, indent=2), encoding="utf-8")


def table(rows):
    f = lambda v, n=3: "–" if v is None else f"{v:.{n}f}"
    print("| Run | Device | Circuit | Compiler | Verdict | ESP ratio | Predicted 1-TVD | Measured 1-TVD"
          " | Measured ratio | Naive test on hardware |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['run']} | {r['device']} | {r['circuit']} | {r['mode']} | {r['verdict']} | {f(r['esp_ratio'])}"
              f" | {f(r['predicted_one_minus_tvd'])} | {f(r['measured_one_minus_tvd'])} | {f(r['measured_ratio'])}"
              f" | {'pass' if r['naive_hw_passed'] else 'fail'} |")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows = load()
    with CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    chart(rows)
    web(rows)
    table(rows)


if __name__ == "__main__":
    main()
