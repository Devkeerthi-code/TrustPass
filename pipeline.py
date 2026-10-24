"""Lock -> untrusted compile -> unlock -> verify -> score.

`seed` only fixes the transpiler for reproducible numbers. The lock itself always draws
from OS entropy: a seed the compiler could guess would let it replay the decoys.
"""
from compilers import COMPILERS, honest
from lock import lock, unlock
from score import confidentiality, overhead, trust
from verify import audit_fidelity, check_function, counts, naive_check, noisy_counts, tvd


def _verify(circuit, locked, backend, mode, seed):
    compiled = COMPILERS[mode](locked.circuit, backend, seed=seed)  # leaves your machine
    final = unlock(compiled, locked.key)                             # back on your machine
    baseline = unlock(honest(locked.circuit, backend, seed=seed), locked.key)
    return final, baseline, check_function(circuit, final), audit_fidelity(final, backend, baseline)


def run(circuit, backend, mode="honest", decoys=0, seed=7, evidence=True, locked=None, conf=None):
    """Pass `locked`/`conf` to reuse one lock across compiler modes (the app does)."""
    locked = locked or lock(circuit, decoys=decoys)
    final, baseline, functional, fidelity = _verify(circuit, locked, backend, mode, seed)
    conf = conf or confidentiality(circuit, locked)
    report = {
        "mode": mode,
        "naive": naive_check(circuit, final),
        "functional": functional,
        "fidelity": fidelity,
        "confidentiality": conf,
        "overhead": overhead(circuit, locked, backend, seed=seed),
        "trust": trust(functional, fidelity, conf),
        "circuits": {"original": circuit, "locked": locked.circuit, "final": final},
    }
    if evidence:  # the same circuits on a simulated noisy copy of the device
        hist = {"ideal": counts(circuit, shots=4000),
                "returned": noisy_counts(final, backend), "baseline": noisy_counts(baseline, backend)}
        report["noisy_fidelity"] = {k: round(1 - tvd(hist["ideal"], hist[k]), 4) for k in ("returned", "baseline")}
        report["histograms"] = hist
    return report


def detection_matrix(circuit, backend, decoys=0, seed=7, locked=None):
    """Which check catches which attack: the one table the pitch is built on.

    Pass `locked` to judge the same lock a run used (the app does, so panel and matrix agree).
    """
    locked = locked or lock(circuit, decoys=decoys)
    rows = []
    for mode in COMPILERS:
        final, _, functional, fidelity = _verify(circuit, locked, backend, mode, seed)
        rows.append({"mode": mode, "naive_test": naive_check(circuit, final)["passed"],
                     "equivalence": functional["passed"], "fidelity_audit": fidelity["passed"],
                     "verdict": "ACCEPT" if functional["passed"] and fidelity["passed"] else "REJECT"})
    return rows
