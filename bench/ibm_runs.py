"""Real IBM hardware runs with a budget guard: does the audit's prediction match the device?

  python bench/ibm_runs.py A         ibm_fez: all 5 compilers x Grover, QAOA, VQE, one SamplerV2 job
  python bench/ibm_runs.py B         Grover honest + saboteur on ibm_kingston and on ibm_marrakesh,
                                     one job per device (--device ibm_kingston for one of them)
  python bench/ibm_runs.py fetch F   collect the results of the job saved in bench JSON F

Prints the account's remaining QPU time first and stops under 4 minutes. One fresh lock (OS entropy)
per circuit, shared by its compilers; transpiler seed 7; 2000 shots. Before running, every circuit is
verified against the device's live target (QCEC + ESP audit against the honest compile of the same
lock) and simulated on AerSimulator.from_backend(device) (predicted 1-TVD). Before each submit the
plan is printed and the script asks for y. After the job: measured 1-TVD against the exact ideal
distribution, and the naive |0> test on the measured histogram (TVD < 0.10). The JSON is written
with the job ID as soon as the job is submitted, then completed with the counts.
Needs a saved IBM Quantum account.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qiskit.quantum_info import Statevector
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2

from circuits import DEMOS
from compilers import COMPILERS
from lock import lock, unlock
from verify import NAIVE_TOL, audit_fidelity, check_function, noisy_counts, tvd

SHOTS, SEED, MIN_SECONDS = 2000, 7, 240
JOBS = {"A": [("ibm_fez", list(DEMOS), list(COMPILERS))],
        "B": [(d, [next(iter(DEMOS))], ["honest", "saboteur"]) for d in ("ibm_kingston", "ibm_marrakesh")]}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def remaining(service):
    u = service.usage()
    left = u.get("usage_remaining_seconds")
    print(f"QPU time: {u.get('usage_consumed_seconds')} s used, {left} s remaining of {u.get('usage_limit_seconds')} s"
          f" (period ends {u.get('usage_period', {}).get('end_time')})")
    return left


def ideal(circuit):
    """Exact output distribution of the original circuit (no sampling noise in the reference)."""
    probs = Statevector(circuit.remove_final_measurements(inplace=False)).probabilities_dict()
    return {k: round(float(v), 6) for k, v in probs.items() if v > 1e-9}


def prepare(backend, names, modes):
    """Lock, compile, unlock and verify every circuit before anything runs."""
    entries, finals = [], []
    for name in names:
        qc = DEMOS[name]()
        locked = lock(qc)  # fresh lock per circuit, shared by its compilers
        compiled = {m: unlock(COMPILERS[m](locked.circuit, backend, seed=SEED), locked.key) for m in modes}
        ref = ideal(qc)
        for mode, final in compiled.items():
            functional = check_function(qc, final)
            fidelity = audit_fidelity(final, backend, compiled["honest"])
            entries.append({"circuit": name, "secret": qc.metadata.get("secret"), "mode": mode,
                            "qcec": functional["verdict"], "audit": fidelity["verdict"],
                            "verdict": "ACCEPT" if functional["passed"] and fidelity["passed"] else "REJECT",
                            "esp": fidelity["esp"], "esp_ratio": fidelity["ratio"], "qubits": fidelity["qubits"],
                            "predicted_one_minus_tvd": round(1 - tvd(ref, noisy_counts(final, backend, shots=SHOTS)), 4),
                            "ideal": ref})
            finals.append(final)
            e = entries[-1]
            print(f"   {name.split(' ')[0]:<7}{mode:<16}{e['verdict']:<8}QCEC {e['qcec']:<31}"
                  f"ESP {e['esp']:.3f} (ratio {e['esp_ratio']:.3f})  predicted 1-TVD {e['predicted_one_minus_tvd']:.3f}")
    return entries, finals


def submit(service, label, device, names, modes):
    backend = service.backend(device)
    calibrated = backend.properties().last_update_date.astimezone(timezone.utc).isoformat(timespec="seconds")
    print(f"\nJob {label}: {device} ({backend.num_qubits} qubits), calibration {calibrated}")
    entries, finals = prepare(backend, names, modes)
    if remaining(service) < MIN_SECONDS:
        sys.exit("Under 4 minutes of QPU time left: not submitting.")
    print(f"Submit to {device}: {len(finals)} circuits x {SHOTS} shots ({backend.status().pending_jobs} jobs queued)?")
    if input("[y/N] ").strip().lower() != "y":
        print("Not submitted.")
        return None
    job = SamplerV2(mode=backend).run(finals, shots=SHOTS)
    out = ROOT / "bench" / f"ibm_{label}_{device}_{now()[:10]}.json"
    out.write_text(json.dumps({"job": label, "device": device, "job_id": job.job_id(), "submitted_utc": now(),
                               "calibration_utc": calibrated, "shots": SHOTS, "transpiler_seed": SEED,
                               "naive_tol": NAIVE_TOL, "circuits": entries}, indent=2), encoding="utf-8")
    print(f"Job {job.job_id()} submitted, saved {out.relative_to(ROOT)}; waiting for results...")
    return out


def fetch(service, path):
    data = json.loads(path.read_text(encoding="utf-8"))
    job = service.job(data["job_id"])
    results = job.result()
    data["finished_utc"] = now()
    try:
        data["qpu_seconds"] = job.usage()
    except Exception:
        pass
    honest = {}
    for e, res in zip(data["circuits"], results):
        got = res.join_data().get_counts()
        d = tvd(e["ideal"], got)
        e.update(counts=got, measured_one_minus_tvd=round(1 - d, 4),
                 naive_hw_tvd=round(d, 4), naive_hw_passed=d < NAIVE_TOL)
        if isinstance(e["secret"], str):
            e["p_secret"] = round(got.get(e["secret"], 0) / data["shots"], 4)
        if e["mode"] == "honest":
            honest[e["circuit"]] = e["measured_one_minus_tvd"]
    for e in data["circuits"]:  # measured counterpart of the ESP ratio: same lock, same device
        e["measured_ratio"] = round(e["measured_one_minus_tvd"] / honest[e["circuit"]], 3)
        print(f"   {e['circuit'].split(' ')[0]:<7}{e['mode']:<16}{e['verdict']:<8}ESP ratio {e['esp_ratio']:.3f}"
              f"  predicted {e['predicted_one_minus_tvd']:.3f}  measured {e['measured_one_minus_tvd']:.3f}"
              f" (ratio {e['measured_ratio']:.3f})  naive on hardware {'pass' if e['naive_hw_passed'] else 'fail'}")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Saved {path.relative_to(ROOT)} (job {data['job_id']}, QPU {data.get('qpu_seconds')} s)")


def main():
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    args = sys.argv[1:]
    if not args or args[0] not in ("A", "B", "fetch"):
        sys.exit(__doc__)
    service = QiskitRuntimeService()
    if remaining(service) < MIN_SECONDS:
        sys.exit("Under 4 minutes of QPU time left: stopping.")
    if args[0] == "fetch":
        return fetch(service, Path(args[1]))
    only = args[args.index("--device") + 1] if "--device" in args else None
    for device, names, modes in JOBS[args[0]]:
        if only in (None, device):
            out = submit(service, args[0], device, names, modes)
            if out:
                fetch(service, out)
    remaining(service)


if __name__ == "__main__":
    main()
