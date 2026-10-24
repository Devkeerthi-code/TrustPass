"""Scaling: what lock, compile, QCEC and the fidelity audit cost as QAOA grows.

One-layer QAOA MaxCut on a random 3-regular graph (graph seed = n, so the inputs are fixed;
the lock still draws OS entropy) at 4-20 qubits, compiled honestly for FakeBrisbane. QCEC runs
twice: the pipeline's check_function (30 s QCEC timeout, then REJECT) and raw QCEC with 110 s.
Each size runs in its own process; a step that takes over 120 s stops that size and is
recorded as a timeout. Writes bench/scaling.csv and bench/scaling.png.
    python bench/scaling.py            (~6 min; --chart redraws the PNG from the CSV)
"""
import csv
import multiprocessing as mp
import queue
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SIZES, STEP_LIMIT = (4, 6, 8, 10, 14, 20), 120
CSV, PNG = ROOT / "bench" / "scaling.csv", ROOT / "bench" / "scaling.png"
FIELDS = ["qubits", "edges", "lock_s", "visible_cx", "decoy_pairs", "compile_s", "compiled_2q",
          "qcec_s", "qcec_verdict", "audit_s", "audit_verdict", "qcec_110_s", "qcec_110_verdict", "status"]


def worker(n, out):
    """Run the pipeline steps for one size, reporting each result as soon as it exists."""
    import rustworkx as rx
    from mqt import qcec
    from qiskit_ibm_runtime.fake_provider import FakeBrisbane

    from circuits import qaoa_maxcut
    from compilers import honest
    from lock import lock, unlock
    from verify import audit_fidelity, check_function

    edges = sorted(tuple(sorted(e)) for e in rx.random_regular_graph(n, 3, seed=n).edge_list())
    circuit, backend = qaoa_maxcut(edges=edges, n=n), FakeBrisbane()
    out.put({"qubits": n, "edges": len(edges)})

    t = time.perf_counter()
    locked = lock(circuit)
    visible = sum(1 for i in locked.circuit.data if i.operation.name == "cx")
    out.put({"lock_s": time.perf_counter() - t, "visible_cx": visible, "decoy_pairs": locked.decoys})

    t = time.perf_counter()
    compiled = honest(locked.circuit, backend, seed=7)
    two_q = sum(v for k, v in compiled.count_ops().items() if k in ("cx", "cz", "ecr"))
    out.put({"compile_s": time.perf_counter() - t, "compiled_2q": two_q})

    final = unlock(compiled, locked.key)
    t = time.perf_counter()
    functional = check_function(circuit, final)  # the pipeline's own check, incl. its 30 s QCEC timeout
    out.put({"qcec_s": time.perf_counter() - t, "qcec_verdict": functional["verdict"]})

    t = time.perf_counter()
    fidelity = audit_fidelity(final, backend, final)  # the ESP pass itself; the baseline compile is compile_s
    out.put({"audit_s": time.perf_counter() - t, "audit_verdict": fidelity["verdict"]})

    t = time.perf_counter()  # would a longer QCEC timeout than the pipeline's 30 s settle it?
    res = qcec.verify(circuit, final, run_zx_checker=False, parallel=False, timeout=STEP_LIMIT - 10)
    out.put({"qcec_110_s": time.perf_counter() - t, "qcec_110_verdict": str(res.equivalence).split(".")[-1],
             "status": "ok"})


def measure(n):
    out = mp.Queue()
    proc = mp.Process(target=worker, args=(n, out), daemon=True)
    proc.start()
    row = {}
    while row.get("status") != "ok":
        try:
            row.update(out.get(timeout=STEP_LIMIT))
        except queue.Empty:
            done = [f for f in FIELDS if f in row]
            row["status"] = "error" if not proc.is_alive() else f"timeout after {done[-1] if done else 'start'}"
            break
    proc.kill()
    row.setdefault("qubits", n)
    return {k: round(v, 3) if isinstance(v, float) else v for k, v in row.items()}


def chart(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
    ink, muted, surface = "#0b0b0b", "#52514e", "#fcfcfb"
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4), facecolor=surface)
    for key, label, c in zip(("lock_s", "compile_s", "qcec_s", "audit_s"),
                             ("lock", "compile (level 3)", "QCEC check", "ESP audit"), colors):
        pts = [(r["qubits"], r[key]) for r in rows if isinstance(r.get(key), float)]
        if pts:
            a.plot(*zip(*pts), color=c, lw=2, marker="o", ms=5, label=label)
    for r in rows:  # the pipeline's check gave up: no proof, so an honest compile would be REJECTed
        if r.get("qcec_verdict") not in (None, "equivalent", "equivalent_up_to_global_phase"):
            a.annotate("30 s cap, no proof",(r["qubits"], r["qcec_s"]), textcoords="offset points",
                       xytext=(0, -16), ha="center", fontsize=8, color=muted)
    a.set_yscale("log")
    a.set_ylabel("seconds (log)", color=muted)
    a.set_title("Time per step", color=ink, fontsize=11, loc="left")
    for key, label, c in zip(("visible_cx", "compiled_2q"), ("visible CX after padding", "compiled 2q gates"),
                             colors):
        pts = [(r["qubits"], r[key]) for r in rows if isinstance(r.get(key), int)]
        if pts:
            b.plot(*zip(*pts), color=c, lw=2, marker="o", ms=5, label=label)
    b.set_ylabel("gates", color=muted)
    b.set_title("Gate counts", color=ink, fontsize=11, loc="left")
    for ax in (a, b):
        ax.set_facecolor(surface)
        ax.set_xlabel("qubits (QAOA, random 3-regular graph)", color=muted)
        ax.set_xticks(SIZES)
        ax.grid(axis="y", color="#e6e5e0", lw=0.8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=muted)
        ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(PNG, dpi=120)


def main():
    if "--chart" in sys.argv:  # redraw from the CSV without re-measuring
        num = lambda v: int(v) if v.isdigit() else float(v) if v.replace(".", "", 1).isdigit() else v
        chart([{k: num(v) for k, v in r.items() if v} for r in csv.DictReader(CSV.open())])
        return
    rows = []
    for n in SIZES:
        rows.append(measure(n))
        print(rows[-1], flush=True)
    with CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    chart(rows)


if __name__ == "__main__":
    main()
