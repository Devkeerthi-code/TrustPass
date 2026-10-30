"""Predicted vs measured: every real IBM hardware run in bench/, in one chart and one table.

Reads bench/ibm_*.json (run 1 from `demo.py --ibm`, the rest from bench/ibm_runs.py) and the panel's
bench/live_ibm/*.json (server.py --allow-ibm); jobs still queued are skipped. A panel job's honest
baseline is the audit's reference, so it has no verdict or ESP ratio of its own ("–"). Measured ratio = measured 1-TVD / the honest compile's measured 1-TVD for the
same lock on the same device, the hardware counterpart of the ESP ratio. Run 1 recorded no noisy-sim
prediction, and its 1-TVD is against a 4,000-shot ideal sample instead of the exact distribution.
The [low, high] intervals are 95% bootstraps over the measured counts (bench/confidence.py).
Jobs S and T of bench/ibm_runs.py (the transpiler-seed sweep) are summarised per device instead of row by row.
The accuracy summary pools every measured circuit (all runs and the sweep): verdicts, the histogram test,
noisy-simulator prediction vs measured 1-TVD, and ESP ratio vs measured ratio for the saboteurs.
Writes bench/hardware.csv, bench/compare.png and web/hardware.json, and prints the README tables.
    python bench/compare.py
"""
import csv
import json
import sys
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from confidence import circuits, done, intervals, jobs
from verify import NAIVE_TOL

CSV, PNG, WEB = ROOT / "bench" / "hardware.csv", ROOT / "bench" / "compare.png", ROOT / "web" / "hardware.json"
FIELDS = ["run", "device", "job_id", "submitted_utc", "circuit", "mode", "verdict", "esp_ratio",
          "predicted_one_minus_tvd", "measured_one_minus_tvd", "measured_ratio", "naive_hw_passed"]
CI = ["measured_ci_low", "measured_ci_high", "ratio_ci_low", "ratio_ci_high"]
MODES = ("honest", "trojan-overt", "trojan-masked", "trojan-dormant", "saboteur")
COLORS = dict(zip(MODES, ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4")))
MARKERS = dict(zip(MODES, ("o", "s", "^", "v", "D")))


def load():
    rows = []
    for d in jobs():
        if not done(d):
            continue
        first = len(rows)
        if "results" in d:  # server.py --allow-ibm panel job: judge, then its honest baseline
            res, fid = d["results"], d["checks"]["fidelity"]
            for (name, mode, _, _), k in zip(circuits(d), ("judge", "baseline")):
                judge = k == "judge"
                rows.append({"device": d["device"], "job_id": d["job_id"], "submitted_utc": d["submitted_utc"],
                             "circuit": name, "mode": mode, "verdict": d["verdict"] if judge else None,
                             "esp_ratio": fid["ratio"] if judge else None,
                             "predicted_one_minus_tvd": d["predicted_one_minus_tvd"][k],
                             "measured_one_minus_tvd": res[k]["one_minus_tvd"],
                             "measured_ratio": res["measured_ratio"] if judge else 1.0,
                             "naive_hw_passed": res[k]["naive_passed"]})
        elif "runs" in d:  # demo.py --ibm: honest + saboteur, one circuit
            honest = d["runs"]["honest"]["one_minus_tvd"]
            for mode, r in d["runs"].items():
                rows.append({"device": d["device"], "job_id": d["job_id"], "submitted_utc": d["submitted_utc"],
                             "circuit": d["circuit"], "mode": mode, "verdict": r["verdict"],
                             "esp_ratio": r["esp_ratio"], "predicted_one_minus_tvd": None,
                             "measured_one_minus_tvd": r["one_minus_tvd"],
                             "measured_ratio": round(r["one_minus_tvd"] / honest, 3),
                             "naive_hw_passed": 1 - r["one_minus_tvd"] < NAIVE_TOL})
        else:
            rows += [{"device": d["device"], "job_id": d["job_id"], "submitted_utc": d["submitted_utc"],
                      **{k: e[k] for k in FIELDS[4:]}} for e in d["circuits"]]
        for r, ci in zip(rows[first:], intervals(d)):  # same circuit order as the rows above
            r.update(zip(CI, ci))
    ids = sorted({(r["submitted_utc"], r["job_id"]) for r in rows})
    for r in rows:
        r["run"] = ids.index((r["submitted_utc"], r["job_id"])) + 1
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


def sweep_ids():
    """Job IDs of the transpiler-seed sweep (bench/ibm_runs.py S and T)."""
    return {d["job_id"] for d in jobs() if d.get("job") in ("S", "T")}


def sweep(rows):
    """Per device: verdicts, saboteur measured ratios and histogram-test passes over the seed sweep."""
    ids, out = sweep_ids(), []
    for device in sorted({r["device"] for r in rows if r["job_id"] in ids}):
        rs = [r for r in rows if r["job_id"] in ids and r["device"] == device]
        mode = lambda m: [r for r in rs if r["mode"] == m]
        sab = sorted(mode("saboteur"), key=lambda r: r["measured_ratio"])
        out.append({"device": device, "jobs": len({r["job_id"] for r in rs}), "circuits": len(rs),
                    "honest_accept": [sum(r["verdict"] == "ACCEPT" for r in mode("honest")), len(mode("honest"))],
                    "reject": {m: [sum(r["verdict"] == "REJECT" for r in mode(m)), len(mode(m))] for m in MODES[1:]},
                    "saboteur_ratio": [[r["measured_ratio"], r["ratio_ci_low"], r["ratio_ci_high"]] for r in (sab[0], sab[-1])],
                    "saboteur_significant": [sum(r["ratio_ci_high"] < 1 for r in sab), len(sab)],
                    "naive_pass": {m: [sum(bool(r["naive_hw_passed"]) for r in mode(m)), len(mode(m))] for m in MODES}})
    return out


def accuracy(rows):
    """One summary over every measured circuit: how right were the verdicts and the predictions?"""
    from scipy.stats import spearmanr
    honest = [r for r in rows if r["mode"] == "honest"]
    attack = [r for r in rows if r["mode"] != "honest"]
    judged = [r for r in honest if r["verdict"]]  # the panel's baseline is not judged
    pred = [r for r in rows if r["predicted_one_minus_tvd"] is not None]
    gap = sorted(round(r["measured_one_minus_tvd"] - r["predicted_one_minus_tvd"], 3) for r in pred)
    sab = [r for r in rows if r["mode"] == "saboteur"]
    rho = lambda x, y: round(float(spearmanr(x, y).statistic), 3)
    pair = lambda xs, n: [sum(xs), n]
    return {"circuits": len(rows), "jobs": len({r["job_id"] for r in rows}),
            "devices": sorted({r["device"] for r in rows}),
            "honest_accept": pair([r["verdict"] == "ACCEPT" for r in judged], len(judged)),
            "attack_reject": pair([r["verdict"] == "REJECT" for r in attack], len(attack)),
            "saboteur_accepted": [{"run": r["run"], "device": r["device"], "circuit": r["circuit"],
                                   "esp_ratio": r["esp_ratio"], "measured_ratio": r["measured_ratio"]}
                                  for r in sab if r["verdict"] == "ACCEPT"],
            "histogram_honest_flagged": pair([not r["naive_hw_passed"] for r in honest], len(honest)),
            "histogram_attack_missed": pair([bool(r["naive_hw_passed"]) for r in attack], len(attack)),
            "sim": {"circuits": len(pred), "gap_min": gap[0], "gap_max": gap[-1],
                    "median_abs_gap": round(median(abs(g) for g in gap), 3),
                    "below_prediction": sum(g < 0 for g in gap),
                    "spearman": rho([r["predicted_one_minus_tvd"] for r in pred], [r["measured_one_minus_tvd"] for r in pred])},
            "saboteur": {"circuits": len(sab), "measured_worse": sum(r["measured_ratio"] < 1 for r in sab),
                         "significantly_worse": sum(r["ratio_ci_high"] < 1 for r in sab),
                         "esp_bigger_loss": sum(r["esp_ratio"] < r["measured_ratio"] for r in sab),
                         "esp_range": [min(r["esp_ratio"] for r in sab), max(r["esp_ratio"] for r in sab)],
                         "measured_range": [min(r["measured_ratio"] for r in sab), max(r["measured_ratio"] for r in sab)],
                         "spearman": rho([r["esp_ratio"] for r in sab], [r["measured_ratio"] for r in sab])}}


def accuracy_table(a):
    f = lambda xy: f"{xy[0]}/{xy[1]}"
    s, b = a["sim"], a["saboteur"]
    print(f"\nAccuracy on real hardware: {a['circuits']} circuits, {a['jobs']} jobs, {', '.join(a['devices'])}")
    print("| Check | Result |\n|---|---|")
    print(f"| Honest compiles ACCEPTed | {f(a['honest_accept'])} |")
    print(f"| Attacks REJECTed | {f(a['attack_reject'])} |")
    print(f"| Histogram test: honest wrongly flagged | {f(a['histogram_honest_flagged'])} |")
    print(f"| Histogram test: attacks missed | {f(a['histogram_attack_missed'])} |")
    print(f"| Noisy simulator vs measured 1-TVD ({s['circuits']} circuits) | gap {s['gap_min']:+.3f} to {s['gap_max']:+.3f},"
          f" median absolute gap {s['median_abs_gap']:.3f}, measured below prediction on {s['below_prediction']},"
          f" Spearman {s['spearman']:.3f} |")
    print(f"| Saboteurs measured worse than honest ({b['circuits']}) | {b['measured_worse']}/{b['circuits']}"
          f" ({b['significantly_worse']} significantly) |")
    print(f"| ESP ratio predicted a bigger loss than measured | {b['esp_bigger_loss']}/{b['circuits']}"
          f" (ESP {b['esp_range'][0]:.3f}-{b['esp_range'][1]:.3f}, measured {b['measured_range'][0]:.3f}-"
          f"{b['measured_range'][1]:.3f}), Spearman {b['spearman']:.3f} |")
    for r in a["saboteur_accepted"]:
        print(f"Saboteur ACCEPTED: run {r['run']} {r['device']} {r['circuit']} ESP ratio {r['esp_ratio']:.3f},"
              f" measured ratio {r['measured_ratio']:.3f}")


def web(rows, summary):
    """Honest vs saboteur, per device and circuit, for the site's hardware block, plus the seed-sweep summary."""
    out, ids = [], sweep_ids()
    for r in rows:
        if r["mode"] != "saboteur" or r["job_id"] in ids:
            continue
        h = next(x for x in rows if x["run"] == r["run"] and x["circuit"] == r["circuit"] and x["mode"] == "honest")
        out.append({"run": r["run"], "device": r["device"], "date": r["submitted_utc"][:10], "job_id": r["job_id"],
                    "circuit": r["circuit"], "honest": {"verdict": h["verdict"], "measured": h["measured_one_minus_tvd"]},
                    "saboteur": {"verdict": r["verdict"], "measured": r["measured_one_minus_tvd"],
                                 "esp_ratio": r["esp_ratio"]}})
    WEB.write_text(json.dumps({"metric": "measured 1-TVD vs ideal", "runs": out, "sweep": summary,
                               "accuracy": accuracy(rows)}, indent=2), encoding="utf-8")


def table(rows):
    f = lambda v, n=3: "–" if v is None else f"{v:.{n}f}"
    ci = lambda r, v, lo, hi: f(r[v]) if r["mode"] == "honest" and v == "measured_ratio" else f"{f(r[v])} [{f(r[lo])}, {f(r[hi])}]"
    print("| Run | Device | Circuit | Compiler | Verdict | ESP ratio | Predicted 1-TVD | Measured 1-TVD [95% CI]"
          " | Measured ratio [95% CI] | Naive test on hardware |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    ids = sweep_ids()
    for r in rows:
        if r["job_id"] in ids:
            continue
        print(f"| {r['run']} | {r['device']} | {r['circuit']} | {r['mode']} | {r['verdict'] or '–'} | {f(r['esp_ratio'])}"
              f" | {f(r['predicted_one_minus_tvd'])} | {ci(r, 'measured_one_minus_tvd', *CI[:2])}"
              f" | {ci(r, 'measured_ratio', *CI[2:])}"
              f" | {'pass' if r['naive_hw_passed'] else 'fail'} |")


def sweep_table(summary):
    f = lambda xy: f"{xy[0]}/{xy[1]}"
    print("\n| Device | Jobs | Circuits | Honest ACCEPT | trojan-overt REJECT | trojan-masked REJECT | trojan-dormant REJECT"
          " | saboteur REJECT | Saboteur measured ratio, lowest / highest [95% CI] | Histogram test passed: honest"
          " / overt / masked / dormant / saboteur |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for s in summary:
        lo, hi = (f"{r:.3f} [{a:.3f}, {b:.3f}]" for r, a, b in s["saboteur_ratio"])
        print(f"| {s['device']} | {s['jobs']} | {s['circuits']} | {f(s['honest_accept'])} | "
              + " | ".join(f(s["reject"][m]) for m in MODES[1:]) + f" | {lo} / {hi} | "
              + " / ".join(f(s["naive_pass"][m]) for m in MODES) + " |")
    pending = [(d["device"], d["job_id"]) for d in jobs() if not done(d)]
    if pending:
        print("\nPending: " + ", ".join(f"{dev} `{j}`" for dev, j in pending))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows = load()
    with CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS + CI, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    chart(rows)
    summary = sweep(rows)
    web(rows, summary)
    table(rows)
    sweep_table(summary)
    accuracy_table(accuracy(rows))


if __name__ == "__main__":
    main()
