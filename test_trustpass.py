"""TrustPass checks. Run: python test_trustpass.py (or pytest). ~10 s."""
import copy
import os
import tempfile

from qiskit import qasm3, transpile
from qiskit.circuit import CircuitInstruction, Delay, ParameterExpression, Reset
from qiskit.circuit.library import CXGate, ECRGate, RZGate
from qiskit.quantum_info import Operator
from qiskit_ibm_runtime.fake_provider import FakeBrisbane, FakeTorino

import pipeline
from circuits import DEMOS, VARIANTS, grover
from compilers import honest, saboteur, worst_region
from lock import lock, random_key, unlock
from pipeline import detection_matrix
from score import confidentiality, secret_blind
import cli
import receipt
from verify import audit_fidelity, check_function, recheck

# mode -> (naive_test, equivalence, fidelity_audit, verdict): the pitch table
EXPECTED = {
    "honest":         (True,  True,  True,  "ACCEPT"),
    "trojan-overt":   (False, False, True,  "REJECT"),
    "trojan-masked":  (True,  False, True,  "REJECT"),
    "trojan-dormant": (True,  False, True,  "REJECT"),
    "saboteur":       (True,  True,  False, "REJECT"),
}


def _op(circ):
    return Operator(circ.remove_final_measurements(inplace=False))


def test_lock_unlock_roundtrip():
    for name, make in DEMOS.items():
        qc = make()
        locked = lock(qc)
        assert _op(unlock(locked.circuit, locked.key)).equiv(_op(qc)), name
        assert not _op(unlock(locked.circuit, random_key(locked, seed=1))).equiv(_op(qc)), name
        assert set(locked.circuit.count_ops()) <= {"rz", "sx", "cx", "barrier", "measure"}, name
        rz = [i.operation.params[0] for i in locked.circuit.data if i.operation.name == "rz"]
        assert rz and all(isinstance(a, ParameterExpression) for a in rz), name


def test_locked_circuit_reveals_only_a_uniform_skeleton():
    # Red-team regressions: metadata/name carried the secret, global phase leaked a bit,
    # and uneven CX counts per qubit pair revealed the QAOA graph.
    for name, make in DEMOS.items():
        qc = make()
        locked = lock(qc)
        assert locked.circuit.metadata == {} and locked.circuit.name == "locked", name
        assert float(locked.circuit.global_phase) == 0, name
        c = confidentiality(qc, locked, guesses=2, inputs=1)
        assert c["metadata_clean"] and c["pair_count_spread"] == 0, (name, c)


def test_unlock_rejects_partial_key():
    locked = lock(grover())
    try:
        unlock(locked.circuit, dict(list(locked.key.items())[1:]))
    except ValueError:
        return
    assert False, "unlock accepted a key with a missing angle"


def _matrix(backend):
    rows = detection_matrix(grover(), backend)
    return {r["mode"]: (r["naive_test"], r["equivalence"], r["fidelity_audit"], r["verdict"]) for r in rows}


def test_detection_matrix_ecr():  # Eagle, native 2q gate = ecr
    got = _matrix(FakeBrisbane())
    assert got == EXPECTED, got


def test_detection_matrix_cz():  # Heron, native 2q gate = cz
    got = _matrix(FakeTorino())
    assert got == EXPECTED, got


def test_verifier_fails_closed():
    # Red-team regressions: a dropped (or swapped-in) measurement passed QCEC, and a single
    # delay or reset crashed the verifier. Honest must still pass, every time (QCEC used to race).
    be, qc = FakeBrisbane(), grover()
    locked = lock(qc)
    final = unlock(honest(locked.circuit, be), locked.key)
    assert all(check_function(qc, final)["passed"] for _ in range(5))
    measures = [i for i, inst in enumerate(final.data) if inst.operation.name == "measure"]
    dropped = final.copy()
    del dropped.data[measures[0]]
    swapped = dropped.copy()  # same measurement count: measure another qubit twice instead
    swapped.data.insert(measures[0], CircuitInstruction(final.data[measures[0]].operation,
                                                        final.data[measures[1]].qubits,
                                                        final.data[measures[0]].clbits))
    delayed = final.copy()
    delayed.data.insert(1, CircuitInstruction(Delay(100_000), [final.qubits[0]]))
    phased = final.copy()  # relative-phase Trojan: rz on an output qubit right before its measurement
    phased.data.insert(measures[0], CircuitInstruction(RZGate(0.35), final.data[measures[0]].qubits))
    reset = final.copy()
    reset.data.insert(measures[0], CircuitInstruction(Reset(), final.data[measures[0]].qubits))
    for bad in (dropped, swapped, phased, reset):
        assert not check_function(qc, bad)["passed"]
    # Delays are logically identity, so QCEC now checks the circuit without them; this 100,000 dt delay
    # stretches the schedule and is REJECTed by the fidelity audit's idle-time charge instead.
    assert check_function(qc, delayed)["passed"]
    assert audit_fidelity(delayed, be, final)["verdict"] == "low_fidelity"
    # Self-cancelling pair on an uncoupled pair: equivalent, but ESP scored the ops as error-free.
    cmap = be.target.build_coupling_map()
    a, b = next((a, b) for a in range(be.num_qubits) for b in range(a)
                if not cmap.graph.has_edge(a, b) and not cmap.graph.has_edge(b, a))
    for gate in (CXGate(), ECRGate()):  # not a device gate at all / the native gate on the wrong pair
        padded = final.copy()
        for _ in range(2):
            padded.data.insert(0, CircuitInstruction(gate, [final.qubits[a], final.qubits[b]]))
        assert check_function(qc, padded)["passed"]  # so only the fidelity audit can catch it
        assert audit_fidelity(padded, be, final)["verdict"] == "not_native"


def test_scheduled_compile_accepted():
    # An honest ALAP-scheduled compile (delays on every idle stretch) is verified, not falsely rejected.
    be, qc = FakeBrisbane(), grover()
    locked = lock(qc)
    baseline = unlock(honest(locked.circuit, be), locked.key)
    scheduled = unlock(transpile(locked.circuit, be, optimization_level=3, seed_transpiler=7,
                                 scheduling_method="alap"), locked.key)
    assert any(inst.operation.name == "delay" for inst in scheduled.data)
    assert check_function(qc, scheduled)["passed"]
    assert audit_fidelity(scheduled, be, baseline)["passed"]


def test_view_never_depends_on_the_secret():
    # Grover's marked item, VQE's weights and QAOA's angles must not change what the compiler sees.
    for name, variants in VARIANTS.items():
        assert secret_blind(variants()), name
    # ...and the check can fail: QAOA's graph is structure, hidden only statistically.
    from circuits import qaoa_maxcut
    assert not secret_blind([qaoa_maxcut(), qaoa_maxcut(edges=((0, 1), (2, 3)))])
    c = confidentiality(grover(), lock(grover()))
    assert c["indistinguishability"] >= 0.9, c  # sanity: the key controls the function


def test_lock_refuses_odd_gaps():
    # Red-team round 2: an odd CX gap can't be padded with CX pairs and leaked a BV secret 100%.
    from qiskit import QuantumCircuit
    bv = QuantumCircuit(3)
    bv.cx(0, 2)
    bv.cx(0, 2)
    bv.cx(1, 2)
    try:
        lock(bv)
    except ValueError:
        return
    assert False, "lock padded an odd gap instead of refusing"


def test_recheck_catches_calibration_drift():
    # Time of check vs time of use: the compile passes the audit, then its qubits degrade before the job runs.
    backend, qc = FakeBrisbane(), grover()
    locked = lock(qc)
    baseline = unlock(honest(locked.circuit, backend), locked.key)
    good = worst_region(backend, qc.num_qubits, percentile=0.02)  # a good region (ratio ~1.07), not the baseline's
    final = unlock(transpile(locked.circuit, backend, optimization_level=3, seed_transpiler=7,
                             initial_layout=good), locked.key)
    checked = audit_fidelity(final, backend, baseline)
    assert checked["passed"] and set(checked["qubits"]).isdisjoint(audit_fidelity(baseline, backend, baseline)["qubits"]), checked
    later = copy.deepcopy(backend)
    used = set(checked["qubits"])
    for name in later.target.operation_names:  # raise every error rate that touches the used qubits
        for qargs, props in later.target[name].items():
            if qargs and used & set(qargs) and props is not None and props.error is not None:
                props.error = min(0.5, 4 * props.error)
    assert audit_fidelity(final, backend, baseline)["passed"]  # the original calibration is untouched
    again = recheck(final, baseline, later)
    assert not again["passed"] and again["verdict"] == "low_fidelity", again


def _tmp_home():
    """Point ~/.trustpass at a fresh temporary folder (receipts, keys, signing key)."""
    os.environ["TRUSTPASS_HOME"] = tempfile.mkdtemp(prefix="trustpass-")
    return os.environ["TRUSTPASS_HOME"]


def test_signed_receipt():
    home, be, qc = _tmp_home(), FakeBrisbane(), grover()
    locked = lock(qc)
    returned = honest(locked.circuit, be)
    _, _, functional, fidelity = pipeline._verify(qc, locked, be, "honest", 7)
    report = {"functional": functional, "fidelity": fidelity, "trust": {"verdict": "ACCEPT"}}
    salt = os.urandom(32)
    pub = receipt.keygen(os.path.join(home, "key.pub"))
    signed = receipt.sign(receipt.make_receipt(qc, locked, returned, report, be, salt=salt))
    assert "salt" not in str(signed) and "k000" not in str(signed)  # neither salt nor key is in it
    assert receipt.verify_receipt(signed, pub)
    for field, value in (("verdict", "REJECT"), ("backend", "FakeTorino"), ("key_commitment", "0" * 64)):
        assert not receipt.verify_receipt({**signed, field: value}, pub), field
    assert receipt.open_commitment(signed, locked.key, salt)
    assert not receipt.open_commitment(signed, random_key(locked, seed=1), salt)
    assert not receipt.open_commitment(signed, locked.key, os.urandom(32))


def test_cli_round_trip():
    # trustpass lock -> a compile done elsewhere (plain Qiskit) -> trustpass verify, through files.
    home = _tmp_home()
    path = lambda name: os.path.join(home, name)
    with open(path("in.qasm"), "w") as f:
        f.write(qasm3.dumps(grover()))
    assert cli.main(["lock", path("in.qasm"), "-o", path("locked.qasm")]) == 0
    with open(path("locked.qasm")) as f:
        sent = qasm3.loads(f.read())
    be = FakeBrisbane()
    for compiled, code in ((transpile(sent, be, optimization_level=3, seed_transpiler=7), 0),  # ACCEPT
                           (saboteur(sent, be), 1)):                                        # REJECT
        with open(path("returned.qasm"), "w") as f:
            f.write(qasm3.dumps(compiled))
        assert cli.main(["verify", path("in.qasm"), path("returned.qasm"), "--backend", "FakeBrisbane",
                         "--receipt", path("receipt.json")]) == code
        assert cli.main(["receipt", "verify", path("receipt.json"), "--pubkey", path("signing_key.pub")]) == 0
    assert cli.main(["verify", path("locked.qasm"), path("returned.qasm"), "--backend", "FakeBrisbane"]) == 2  # no key


def test_plant_endpoint():
    # The live demo's "Plant a Trojan": a small rz on a data qubit passes the naive test, never QCEC.
    import json
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    import server
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/api/plant?circuit=grover&backend=FakeBrisbane&pos=middle"
    try:
        r = json.load(urllib.request.urlopen(url + "&gate=rz&qubit=0", timeout=120))
        assert r["verdict"] == "REJECT" and not r["checks"]["equivalence"]["passed"], r
        assert r["planted"]["gate"] == "rz" and r["checks"]["fidelity"]["passed"], r
        for bad in ("&gate=bad&qubit=0", "&gate=h&qubit=0", "&gate=rz&qubit=9", "&gate=rz&qubit=-1"):
            try:
                urllib.request.urlopen(url + bad, timeout=120)
                assert False, bad
            except urllib.error.HTTPError as e:
                assert e.code == 400, (bad, e.code)
    finally:
        httpd.shutdown()


def test_pipeline_never_seeds_the_lock():
    # Red-team round 1: a public seed let the compiler replay the decoys.
    seen = []
    real = pipeline.lock
    pipeline.lock = lambda *a, **k: seen.append(k.get("seed")) or real(*a, **k)
    try:
        pipeline.detection_matrix(grover(), FakeBrisbane(), seed=7)
        pipeline.run(grover(), FakeBrisbane(), seed=7, evidence=False)
    finally:
        pipeline.lock = real
    assert seen and all(s is None for s in seen), seen


if __name__ == "__main__":
    import sys
    import time
    import traceback
    failed = 0
    for name, test in [(k, v) for k, v in globals().items() if k.startswith("test_")]:
        t = time.perf_counter()
        try:
            test()
            print(f"PASS {name} ({time.perf_counter() - t:.1f}s)")
        except Exception:
            failed += 1
            traceback.print_exc()
            print(f"FAIL {name} ({time.perf_counter() - t:.1f}s)")
    print(f"{failed} failed")
    sys.exit(1 if failed else 0)
