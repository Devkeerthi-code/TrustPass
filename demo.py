"""TrustPass in the terminal: lock -> untrusted compile -> unlock -> verify -> score.

  python demo.py              the whole story (Grover on FakeBrisbane)
  python demo.py --matrix     only the detection matrix
  python demo.py --ibm        honest vs sabotaged compile on real IBM hardware (saved account needed)
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from qiskit.circuit import ParameterExpression
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2, fake_provider

from circuits import DEMOS, VARIANTS
from compilers import COMPILERS
from lock import lock, unlock
from pipeline import detection_matrix, run
from score import secret_blind, view
from verify import audit_fidelity, check_function, counts, tvd

SHOTS = 4000
NO_ACCOUNT = """To run on real IBM hardware, save your own IBM Quantum account once on this machine:
create an API key at https://quantum.cloud.ibm.com, then in Python run
  from qiskit_ibm_runtime import QiskitRuntimeService
  QiskitRuntimeService.save_account(token="<your API key>", set_as_default=True)
(add instance="<your instance CRN>" if you have several). The key stays in ~/.qiskit on your
machine; TrustPass never asks for it, it only uses the account you saved. Then re-run with --ibm."""


def mark(ok):
    return "✓" if ok else "✗"


def matrix(rows):
    print(f"   {'compiler':<16}{'naive |0> test':<17}{'equivalence':<14}{'fidelity audit':<17}verdict")
    for r in rows:
        print(f"   {r['mode']:<16}{mark(r['naive_test']):<17}{mark(r['equivalence']):<14}"
              f"{mark(r['fidelity_audit']):<17}{r['verdict']}")


def story(name, circuit, backend, args):
    r = run(circuit, backend, "saboteur", args.decoys, args.seed)
    c, f, o, locked = r["confidentiality"], r["fidelity"], r["overhead"], r["circuits"]["locked"]
    numeric = sum(not isinstance(p, ParameterExpression) for i in locked.data for p in i.operation.params)

    print("\n1. What the untrusted compiler sees")
    print(f"   key angles (rz parameters)    {c['key_angles']}")
    print(f"   numeric gate angles           {numeric}")
    print(f"   visible 2q gates (CX)         {c['visible_2q_gates']}  ({c['decoy_share_of_2q']:.0%} are decoys)")
    print(f"   name / metadata sent along    {locked.name!r} / {locked.metadata or 'none'}")

    print("\n2. Attacker's view (has the locked circuit, guesses the key)")
    print(f"   indistinguishability          {c['indistinguishability']:.3f}  (1.0 = wrong keys look random: the key controls the function)")
    print(f"   wrong-key TVD, random inputs  {c['wrong_key_tvd_random_inputs']:.3f}"
          f"  (know-nothing reference {c['know_nothing_tvd']:.3f})")
    variants = VARIANTS[name]()
    print(f"   same circuit, {len(variants)} secrets     {len({view(v) for v in variants})} distinct circuits before locking"
          f" -> {'1 identical view after' if secret_blind(variants) else 'views DIFFER after'}")

    print("\n3. Detection matrix (✓ = check passed, ✗ = check failed = attack caught)")
    matrix(detection_matrix(circuit, backend, args.decoys, args.seed))

    print(f"\n4. Saboteur evidence (naive test {mark(r['naive']['passed'])},"
          f" QCEC says {r['functional']['verdict']})")
    print(f"   ESP                           {f['esp']:.3f} returned vs {f['esp_baseline']:.3f}"
          f" local honest compile (ratio {f['ratio']:.2f})")
    nf = r["noisy_fidelity"]
    print(f"   noisy-sim fidelity            {nf['returned']:.3f} returned vs {nf['baseline']:.3f} baseline")
    print(f"   physical qubits used          {f['qubits']}")
    print(f"   their readout error           {f['readout_err_used']:.4f}"
          f" vs device median {f['readout_err_device_median']:.4f}")

    print("\n5. Cost of locking (honest compile, plain vs locked)")
    print(f"   2q gates                      {o['2q_plain']} -> {o['2q_locked']}")
    print(f"   depth                         {o['depth_plain']} -> {o['depth_locked']}")


def ibm(name, circuit, args):
    try:
        service = QiskitRuntimeService()
    except Exception as e:  # no saved account, or it no longer works
        print(f"No usable IBM Quantum account: {e}\n\n{NO_ACCOUNT}")
        sys.exit(1)
    backend = service.least_busy(operational=True, simulator=False)
    print(f"\nReal backend: {backend.name} ({backend.num_qubits} qubits)")
    locked = lock(circuit, decoys=args.decoys)  # OS entropy: never lock with a guessable seed
    finals = {m: unlock(COMPILERS[m](locked.circuit, backend, seed=args.seed), locked.key)
              for m in ("honest", "saboteur")}
    # Full verification before anything runs; the honest compile of the same lock is the baseline.
    checks = {}
    for mode, final in finals.items():
        functional = check_function(circuit, final)
        fidelity = audit_fidelity(final, backend, finals["honest"])
        checks[mode] = {"qcec": functional["verdict"], "audit": fidelity["verdict"],
                        "esp": fidelity["esp"], "esp_ratio": fidelity["ratio"],
                        "verdict": "ACCEPT" if functional["passed"] and fidelity["passed"] else "REJECT"}
    print(f"About to submit {len(finals)} circuits x {SHOTS} shots")
    if len(finals) > 2:
        sys.exit("More than 2 circuits: not submitting.")
    submitted = datetime.now(timezone.utc).isoformat(timespec="seconds")
    job = SamplerV2(mode=backend).run(list(finals.values()), shots=SHOTS)
    print(f"Job {job.job_id()} submitted {submitted}, waiting for results...")
    ideal, secret = counts(circuit, shots=SHOTS), circuit.metadata.get("secret")
    for (mode, final), res in zip(finals.items(), job.result()):
        got, c = res.join_data().get_counts(), checks[mode]
        c.update(counts=got, one_minus_tvd=round(1 - tvd(ideal, got), 4))
        line = (f"   {mode:<9} {c['verdict']}  QCEC {c['qcec']}  ESP {c['esp']:.3f} (ratio {c['esp_ratio']:.2f})"
                f"   1-TVD vs ideal {c['one_minus_tvd']:.3f}")
        if isinstance(secret, str):
            c["p_secret"] = round(got.get(secret, 0) / SHOTS, 4)
            line += f"   P({secret}) {c['p_secret']:.3f}"
        print(line)
    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = Path(__file__).parent / "bench" / f"ibm_{backend.name}_{submitted[:10]}.json"
    out.write_text(json.dumps({"device": backend.name, "job_id": job.job_id(), "submitted_utc": submitted,
                               "finished_utc": finished, "circuit": name, "secret": secret, "shots": SHOTS,
                               "decoys": args.decoys, "transpiler_seed": args.seed, "ideal_counts": ideal,
                               "runs": checks}, indent=2), encoding="utf-8")
    print(f"Saved {out.relative_to(Path(__file__).parent)}")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)  # ✓/✗ on Windows pipes
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--circuit", default="Grover", help=f"start of a demo name: {', '.join(DEMOS)}")
    p.add_argument("--backend", default="FakeBrisbane", help="fake backend class, e.g. FakeTorino")
    p.add_argument("--decoys", type=int, default=0, help="extra decoy rounds on top of pair padding")
    p.add_argument("--seed", type=int, default=7, help="transpiler seed (the lock always uses OS entropy)")
    p.add_argument("--matrix", action="store_true", help="print only the detection matrix")
    p.add_argument("--ibm", action="store_true", help="run honest vs saboteur on the least busy real IBM device")
    args = p.parse_args(argv)
    name = next((k for k in DEMOS if k.lower().startswith(args.circuit.lower())), None)
    if name is None:
        p.error(f"unknown --circuit {args.circuit!r}; choose from {list(DEMOS)}")
    circuit = DEMOS[name]()
    if args.ibm:
        print(f"TrustPass | {name} | real IBM hardware | extra decoys={args.decoys} transpiler seed={args.seed}")
        return ibm(name, circuit, args)
    if not args.backend.startswith("Fake") or not hasattr(fake_provider, args.backend):
        p.error(f"unknown --backend {args.backend!r}; use a class from qiskit_ibm_runtime.fake_provider")
    backend = getattr(fake_provider, args.backend)()
    print(f"TrustPass | {name} | {args.backend} | extra decoys={args.decoys} transpiler seed={args.seed}")
    if args.matrix:
        print("\nDetection matrix (✓ = check passed, ✗ = check failed = attack caught)")
        return matrix(detection_matrix(circuit, backend, args.decoys, args.seed))
    story(name, circuit, backend, args)


if __name__ == "__main__":
    main()
