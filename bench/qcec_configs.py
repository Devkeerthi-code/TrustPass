"""Can another QCEC configuration prove the 14-qubit QAOA case that times out in the pipeline?

Same circuit as bench/scaling.py at 14 qubits (3-regular graph, seed 14; fresh lock; honest compile
for FakeBrisbane, level 3, seed 7). Every configuration runs sequentially (parallel=False) in a
killable worker (QCEC's verify_with_hard_timeout), with a cooperative timeout plus 30 s of slack.
Not tried: the HSF checker, which needs check_approximate_equivalence, so it cannot give a proof.
Writes bench/qcec_configs.csv.
    python bench/qcec_configs.py              (one run per configuration, ~15 min)
    python bench/qcec_configs.py NAME [N]     (N repeats of one configuration, each with a fresh lock)
"""
import csv
import sys
import time
from pathlib import Path

import mqt.qcec
import rustworkx as rx
from mqt.qcec import verify_with_hard_timeout
from mqt.qcec.pyqcec import ApplicationScheme

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qiskit_ibm_runtime.fake_provider import FakeBrisbane  # noqa: E402

from circuits import qaoa_maxcut  # noqa: E402
from compilers import honest  # noqa: E402
from lock import lock, unlock  # noqa: E402

N, CSV = 14, ROOT / "bench" / "qcec_configs.csv"
O3 = str(Path(mqt.qcec.__file__).parent / "profiles" / "qiskit_O3.profile")
SEQ = {"parallel": False}
CONFIGS = {  # name -> (cooperative timeout in s, QCEC options)
    "pipeline, 300 s": (300, {**SEQ, "run_zx_checker": False}),
    "zx on": (120, {**SEQ, "run_zx_checker": True}),
    "zx only": (120, {**SEQ, "method": "zx"}),
    "construction only": (120, {**SEQ, "method": "construction"}),
    "alternating, gate_cost (qiskit O3 profile)": (120, {**SEQ, "method": "alternating", "profile": O3,
                                                         "alternating_scheme": ApplicationScheme.gate_cost}),
    "alternating, lookahead": (120, {**SEQ, "method": "alternating",
                                     "alternating_scheme": ApplicationScheme.lookahead}),
    "alternating, one_to_one": (120, {**SEQ, "method": "alternating",
                                      "alternating_scheme": ApplicationScheme.one_to_one}),
}


def case():
    edges = sorted(tuple(sorted(e)) for e in rx.random_regular_graph(N, 3, seed=N).edge_list())
    circuit, backend = qaoa_maxcut(edges=edges, n=N), FakeBrisbane()
    locked = lock(circuit)
    return circuit, unlock(honest(locked.circuit, backend, seed=7), locked.key)


def run(name):
    timeout, options = CONFIGS[name]
    circuit, final = case()
    t = time.perf_counter()
    try:
        res = verify_with_hard_timeout(circuit, final, timeout + 30, timeout=timeout, **options)
        verdict = str(res["equivalence"]).split(".")[-1]
    except TimeoutError:
        verdict = "killed_at_deadline"
    except Exception as e:  # an unsupported configuration is a result too
        verdict = f"error:{type(e).__name__}:{str(e)[:80]}"
    row = {"config": name, "timeout_s": timeout, "seconds": round(time.perf_counter() - t, 1), "verdict": verdict}
    print(row, flush=True)
    return row


def main():
    names, repeats = (sys.argv[1:2], int(sys.argv[2]) if len(sys.argv) > 2 else 3) if len(sys.argv) > 1 \
        else (list(CONFIGS), 1)
    rows = [run(name) for name in names for _ in range(repeats)]
    new = not CSV.exists()
    with CSV.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        if new:
            w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
