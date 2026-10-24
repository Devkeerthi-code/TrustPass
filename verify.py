"""Checks run by the user on what the compiler sent back."""
import math
import time
import warnings
from functools import lru_cache

import numpy as np
from mqt import qcec
from qiskit.transpiler import PassManager
from qiskit.transpiler.passes import ALAPScheduleAnalysis, PadDelay
from qiskit_aer import AerSimulator

NAIVE_TOL = 0.10        # "looks right" in a histogram; checked on an ideal simulator (best case for this test)
FIDELITY_RATIO = 0.90   # flag if the returned circuit is >10% less likely to succeed than a free baseline


def _outputs(circ, layout=None):
    """clbit -> qubit that is measured into it (mapped through a layout if given)."""
    m = {}
    for inst in circ.data:
        if inst.operation.name == "measure":
            q, c = circ.find_bit(inst.qubits[0]).index, circ.find_bit(inst.clbits[0]).index
            m.setdefault(c, []).append(layout[q] if layout else q)
    return m


def _without_delays(circ):
    """Delays are the identity on the logical state; the fidelity audit charges their idle time."""
    out = circ.copy()
    out.data = [inst for inst in circ.data if inst.operation.name != "delay"]
    return out


def check_function(original, compiled):
    """Formal equivalence check: same unitary for *every* input (up to global phase), same outputs.

    Delays are dropped before QCEC (a scheduled compile is checked as its gate sequence).
    Fails closed: anything else QCEC cannot reason about (reset, feed-forward) is a REJECT.
    """
    t = time.perf_counter()
    done = lambda passed, verdict: {"passed": passed, "verdict": verdict,
                                    "seconds": round(time.perf_counter() - t, 3)}
    try:
        # QCEC treats unmeasured qubits as don't-care, so check the clbit->qubit map ourselves:
        # a dropped or re-routed measurement would otherwise pass.
        if _outputs(compiled) != _outputs(original, compiled.layout.final_index_layout()):
            return done(False, "outputs_changed")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # Sequential, no ZX checker: the parallel checkers can race into 'no_information' or
            # deadlock under load. A timeout turns anything slow into a REJECT, never a hang.
            res = qcec.verify(original, _without_delays(compiled), run_zx_checker=False, parallel=False,
                              timeout=30)
    except Exception as e:
        return done(False, f"unverifiable:{type(e).__name__}")
    crit = str(res.equivalence).split(".")[-1]
    # Not 'equivalent_up_to_phase': that is a *relative* phase, i.e. a different unitary.
    return done(crit in ("equivalent", "equivalent_up_to_global_phase"), crit)


def counts(circ, shots=8192, seed=1, backend=None):
    sim = AerSimulator.from_backend(backend) if backend else AerSimulator()
    return sim.run(circ, shots=shots, seed_simulator=seed).result().get_counts()


def tvd(c1, c2):
    s1, s2 = sum(c1.values()), sum(c2.values())
    return 0.5 * sum(abs(c1.get(k, 0) / s1 - c2.get(k, 0) / s2) for k in set(c1) | set(c2))


def naive_check(original, compiled, tol=NAIVE_TOL):
    """What most users do today: run it on |0...0> and eyeball the histogram (ideal sim: best case for this test)."""
    d = tvd(counts(original), counts(compiled))
    return {"passed": d < tol, "tvd": round(d, 4)}


def esp(circ, target):
    """Estimated success probability: product of (1 - error) over every gate and measurement."""
    p = 1.0
    for inst in circ.data:
        name = inst.operation.name
        if name in ("barrier", "delay"):
            continue
        qargs = tuple(circ.find_bit(q).index for q in inst.qubits)
        props = target[name].get(qargs) if name in target.operation_names else None
        p *= 1.0 - ((props.error or 0.0) if props else 0.0)
    return p


def _active(circ):
    return sorted({circ.find_bit(q).index for inst in circ.data for q in inst.qubits
                   if inst.operation.name not in ("barrier", "delay")})


def _not_native(circ, target):
    """Any op the device can't run (unknown gate, or a 2q gate on an uncoupled pair)? esp() scores those as free."""
    return any(inst.operation.name not in ("barrier", "delay") and not target.instruction_supported(
        inst.operation.name, tuple(circ.find_bit(q).index for q in inst.qubits)) for inst in circ.data)


_UNIT = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12}


def _schedule(circ, target):
    """ALAP-schedule locally: every idle stretch becomes an explicit delay (delays already there stay)."""
    return PassManager([ALAPScheduleAnalysis(target=target), PadDelay(target=target)]).run(circ)


def idle_decay(circ, target):
    """Survival through idle time: the product over delays of exp(-t / min(T1, T2)) of the delayed qubit.

    Only qubits the circuit uses are charged, but every delay on them is, including the leading ones
    of an ALAP schedule (a qubit still in |0> loses nothing there): pessimistic, and applied to both
    sides of the audit alike. A schedule stretched by a delay anywhere thus costs the qubits in use.
    """
    p, used = 1.0, set(_active(circ))
    for inst in circ.data:
        if inst.operation.name == "delay" and circ.find_bit(inst.qubits[0]).index in used:
            d = inst.operation
            t = d.duration * (target.dt if d.unit == "dt" else _UNIT[d.unit])
            q = target.qubit_properties[circ.find_bit(inst.qubits[0]).index]
            p *= math.exp(-t / min(x for x in (q.t1, q.t2) if x))
    return p


def audit_fidelity(compiled, backend, reference, threshold=FIDELITY_RATIO):
    """Is the circuit we got back much less likely to succeed than a free local compile?

    If the compile contains delays, idle time is counted: both it and the reference are ALAP-scheduled
    locally (which adds nothing to an already ALAP-scheduled compile) and scored ESP x idle_decay.
    Fails closed: a circuit with any op the device does not support is a REJECT ('not_native').
    """
    t = backend.target
    ro = np.array([t["measure"][(q,)].error or 0.0 for q in range(t.num_qubits)])
    used = _active(compiled)
    scheduled = any(inst.operation.name == "delay" for inst in compiled.data)
    if _not_native(compiled, t):
        verdict, e, e_ref = "not_native", esp(compiled, t), esp(reference, t)
    else:
        if scheduled:
            compiled, reference = _schedule(compiled, t), _schedule(reference, t)
        score = lambda c: esp(c, t) * (idle_decay(c, t) if scheduled else 1.0)
        e, e_ref = score(compiled), score(reference)
        verdict = "ok" if e_ref and e / e_ref >= threshold else "low_fidelity"
    ratio = e / e_ref if e_ref else 0.0
    return {"passed": verdict == "ok", "verdict": verdict, "esp": round(e, 4), "esp_baseline": round(e_ref, 4),
            "ratio": round(ratio, 3), "qubits": used,
            "readout_err_used": round(float(ro[used].mean()), 4),
            "readout_err_device_median": round(float(np.median(ro)), 4)}


@lru_cache(maxsize=4)
def _noisy_sim(backend):
    return AerSimulator.from_backend(backend)


def noisy_counts(circ, backend, shots=4000, seed=1):
    """Run on a simulated noisy copy of the device (its real calibration data)."""
    return _noisy_sim(backend).run(circ, shots=shots, seed_simulator=seed).result().get_counts()


def noisy_fidelity(original, compiled, backend, shots=4000, seed=1):
    """Evidence on a simulated noisy copy of the device: how close are results to the ideal?"""
    return round(1.0 - tvd(counts(original, shots=shots, seed=seed), noisy_counts(compiled, backend, shots, seed)), 4)
