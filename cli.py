"""trustpass: lock a circuit, verify what an untrusted compiler sent back, check a signed receipt.

  trustpass lock in.qasm -o locked.qasm                          lock with OS entropy, key -> ~/.trustpass/keys
  trustpass verify in.qasm returned.qasm --backend FakeBrisbane   unlock + output map + QCEC + fidelity audit
  trustpass receipt verify receipt.json --pubkey key.pub          VALID / INVALID
  trustpass keygen -o key.pub                                     export the public key of your signing key

QASM 2 and 3 input. ibm_* backends read live calibration only; nothing is ever submitted.
Exit code: 0 = ACCEPT (VALID), 1 = REJECT (INVALID), 2 = error.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from qiskit import QuantumCircuit, QuantumRegister, qasm2, qasm3
from qiskit.circuit import AncillaRegister
from qiskit.transpiler import Layout, TranspileLayout
from qiskit_ibm_runtime import fake_provider

import receipt
from compilers import honest
from lock import Locked, lock, unlock
from verify import FIDELITY_RATIO, _outputs, audit_fidelity, check_function

BACKENDS = ("FakeBrisbane", "FakeTorino", "ibm_fez", "ibm_kingston", "ibm_marrakesh")


class CliError(Exception):
    pass


def load(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise CliError(f"cannot read {path}: {e.strerror}")
    try:
        return qasm2.loads(text) if "OPENQASM 2" in text[:200] else qasm3.loads(text)
    except Exception as e:
        raise CliError(f"{path} is not a readable OpenQASM 2 or 3 circuit: {e}")


def get_backend(name):
    if name.startswith("Fake"):
        return getattr(fake_provider, name)()
    from qiskit_ibm_runtime import QiskitRuntimeService
    try:  # live calibration only: this backend object is never given a job
        return QiskitRuntimeService().backend(name)
    except Exception as e:
        raise CliError(f"cannot reach {name} with your saved IBM Quantum account ({type(e).__name__})")


def find_key(original, path=None):
    if path:
        try:
            return Path(path), json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise CliError(f"cannot read key file {path}: {e}")
    keys = receipt.home() / "keys"
    want = receipt.circuit_sha256(original)
    found = sorted(((p, json.loads(p.read_text(encoding="utf-8"))) for p in keys.glob("*.json")),
                   key=lambda pe: pe[1].get("created_utc", ""))
    found = [(p, e) for p, e in found if e.get("original_sha256") == want]
    if not found:
        raise CliError(f"no lock key for this circuit in {keys}: lock it with `trustpass lock` first, or pass --key")
    if len(found) > 1:
        print(f"note: {len(found)} keys for this circuit, using the newest ({found[-1][0].name}); --key to choose")
    return found[-1]


def bind(circ, key):
    """Bind a name -> angle key into a circuit whose parameters were read back from QASM."""
    params = {p.name: p for p in circ.parameters}
    return unlock(circ, {params[k]: v for k, v in key.items() if k in params})


def with_layout(returned, locked, original, backend):
    """QASM drops the compiler's layout, so rebuild it from the circuit itself.

    Start: where each logical qubit's first key angle appears (a routing SWAP before it gives a
    wrong guess, i.e. a false REJECT, never an ACCEPT: QCEC still checks the whole circuit).
    End: the qubit measured into each of the original's clbits.
    """
    out = QuantumCircuit(QuantumRegister(max(backend.num_qubits, returned.num_qubits), "q"), *returned.cregs)
    out.compose(returned, qubits=range(returned.num_qubits), clbits=returned.clbits, inplace=True)
    n, size = locked.num_qubits, out.num_qubits
    first = {}
    for inst in locked.data:
        q = locked.find_bit(inst.qubits[0]).index
        if q not in first and inst.operation.params:
            first[q] = {p.name for p in inst.operation.params[0].parameters}
    start = {}
    for inst in out.data:
        names = {p.name for x in inst.operation.params if hasattr(x, "parameters") for p in x.parameters}
        for q, mine in first.items():
            if q not in start and names & mine and len(inst.qubits) == 1:
                start[q] = out.find_bit(inst.qubits[0]).index
    measured, wanted = _outputs(out), _outputs(original)
    end = {q: measured.get(c, [start.get(q)])[0] for c, (q,) in wanted.items()}
    end = {q: end.get(q, start.get(q)) for q in range(n)}
    if len(start) != n or len(set(start.values())) != n or len(set(end.values())) != n:
        raise ValueError("cannot locate the data qubits in the returned circuit")
    virtual = list(QuantumRegister(n, "q")) + list(AncillaRegister(size - n, "ancilla"))
    phys = [start[q] for q in range(n)] + [p for p in range(size) if p not in start.values()]
    perm = {start[q]: end[q] for q in range(n)}
    perm.update(zip([p for p in range(size) if p not in perm], [p for p in range(size) if p not in perm.values()]))
    out._layout = TranspileLayout(Layout(dict(zip(virtual, phys))), {b: i for i, b in enumerate(virtual)},
                                  Layout({out.qubits[p]: perm[p] for p in range(size)}),
                                  _input_qubit_count=n, _output_qubit_list=out.qubits)
    return out


def check(original, returned, entry, backend, seed):
    """The verdict on a returned circuit: output map + QCEC and the fidelity audit vs a local honest compile."""
    locked = qasm3.loads(entry["locked_qasm"])
    baseline = bind(honest(locked, backend, seed=seed), entry["key"])
    try:
        final = bind(with_layout(returned, locked, original, backend), entry["key"])
    except ValueError as e:  # unbound or unknown parameters, or no data qubits to be found
        functional = {"passed": False, "verdict": f"unverifiable:{e}"}
        fidelity = {"passed": False, "verdict": "not_run", "esp": None, "esp_baseline": None, "ratio": None}
    else:
        functional, fidelity = check_function(original, final), audit_fidelity(final, backend, baseline)
    verdict = "ACCEPT" if functional["passed"] and fidelity["passed"] else "REJECT"
    return {"functional": functional, "fidelity": fidelity, "trust": {"verdict": verdict}}, locked


def cmd_lock(a):
    original = load(a.circuit)
    try:
        locked = lock(original, decoys=a.decoys)  # OS entropy, never a seed
    except ValueError as e:
        raise CliError(str(e))
    Path(a.output).write_text(qasm3.dumps(locked.circuit), encoding="utf-8")
    key = receipt.save_key(locked, original, os.urandom(32))
    print(f"locked: {len(locked.key)} key angles, {locked.decoys} decoy CX pairs -> {a.output}")
    print(f"key: {key} (stays on this machine)")
    return 0


def cmd_verify(a):
    from server import reason  # the web panel's reason line
    original, returned = load(a.circuit), load(a.returned)
    path, entry = find_key(original, a.key)
    backend = get_backend(a.backend)
    report, locked = check(original, returned, entry, backend, a.seed)
    fn, fd = report["functional"], report["fidelity"]
    mark = lambda ok: "PASS" if ok else "FAIL"
    print(f"TrustPass verify | {a.backend} | key {path.name[:12]}")
    print(f"  output map + QCEC  {mark(fn['passed'])}  {fn['verdict']}" + (f" ({fn['seconds']} s)" if "seconds" in fn else ""))
    if fd["esp"] is None:
        print(f"  fidelity audit     FAIL  not run")
    else:
        print(f"  fidelity audit     {mark(fd['passed'])}  ESP {fd['esp']:.3f} vs {fd['esp_baseline']:.3f} baseline,"
              f" ratio {fd['ratio']:.3f} (threshold {FIDELITY_RATIO:.2f})")
    print(f"  verdict            {report['trust']['verdict']}")
    print(f"  {reason(report)}")
    if not a.no_receipt:
        if not (receipt.home() / "signing_key").exists():
            pub = receipt.keygen(receipt.home() / "signing_key.pub")
            print(f"  new signing key in {receipt.home()}; public key {pub}")
        made = receipt.make_receipt(original, Locked(locked, entry["key"], entry.get("decoys", 0)), returned,
                                    report, backend, salt=bytes.fromhex(entry["salt"]))
        Path(a.receipt).write_text(json.dumps(receipt.sign(made), indent=1), encoding="utf-8")
        print(f"  receipt            {a.receipt} (signed)")
    return 0 if report["trust"]["verdict"] == "ACCEPT" else 1


def cmd_receipt_verify(a):
    try:
        signed = json.loads(Path(a.receipt).read_text(encoding="utf-8"))
        Path(a.pubkey).read_bytes()
    except (OSError, ValueError) as e:
        raise CliError(f"cannot read {e.filename or a.receipt}: {e}")
    ok = receipt.verify_receipt(signed, a.pubkey)
    print("VALID" if ok else "INVALID")
    return 0 if ok else 1


def cmd_keygen(a):
    print(f"public key: {receipt.keygen(a.output)} (private key stays in {receipt.home() / 'signing_key'})")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="trustpass", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("lock", help="lock a circuit before it goes to an untrusted compiler")
    s.add_argument("circuit")
    s.add_argument("-o", "--output", required=True, help="where to write the locked circuit (QASM 3)")
    s.add_argument("--decoys", type=int, default=0, help="extra decoy rounds on top of pair padding")
    s.set_defaults(run=cmd_lock)
    s = sub.add_parser("verify", help="verify a returned compile against your original circuit")
    s.add_argument("circuit", help="your original circuit")
    s.add_argument("returned", help="what the compiler sent back")
    s.add_argument("--backend", required=True, choices=BACKENDS)
    s.add_argument("--key", help="key file (default: found by the original circuit's hash)")
    s.add_argument("--seed", type=int, default=7, help="transpiler seed of the local baseline compile")
    s.add_argument("--receipt", default="receipt.json", help="where to write the signed receipt")
    s.add_argument("--no-receipt", action="store_true")
    s.set_defaults(run=cmd_verify)
    s = sub.add_parser("receipt", help="check a signed receipt")
    rs = s.add_subparsers(dest="action", required=True)
    s = rs.add_parser("verify")
    s.add_argument("receipt")
    s.add_argument("--pubkey", required=True)
    s.set_defaults(run=cmd_receipt_verify)
    s = sub.add_parser("keygen", help="make (or reuse) your signing key and write its public key")
    s.add_argument("-o", "--output", default="trustpass.pub")
    s.set_defaults(run=cmd_keygen)
    a = p.parse_args(argv)
    try:
        return a.run(a)
    except CliError as e:
        print(f"trustpass: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # never exit 1 (= REJECT) on a crash
        print(f"trustpass: error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
