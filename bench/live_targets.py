"""The detection matrix against real IBM devices' live calibration (no jobs, no QPU time).

For each device: fetch the backend (its target carries today's calibration), record the
calibration timestamp, then run pipeline.detection_matrix for Grover, QAOA and VQE, each with
a fresh lock (OS entropy) and transpiler seed 7. The ESP ratio and naive TVD come from
pipeline.run on the same lock (same compile). Needs a saved IBM Quantum account.
Writes bench/live_targets.csv.
    python bench/live_targets.py
"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qiskit_ibm_runtime import QiskitRuntimeService

from circuits import DEMOS
from lock import lock
from pipeline import detection_matrix, run

DEVICES = ("ibm_fez", "ibm_kingston")
CSV = ROOT / "bench" / "live_targets.csv"
FIELDS = ["device", "calibration_utc", "fetched_utc", "circuit", "mode",
          "naive_test", "naive_tvd", "equivalence", "fidelity_audit", "esp_ratio", "verdict"]


def main():
    service = QiskitRuntimeService()
    rows = []
    for name in DEVICES:
        backend = service.backend(name)
        fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
        calibrated = backend.properties().last_update_date.astimezone(timezone.utc).isoformat(timespec="seconds")
        print(f"{name}: calibration {calibrated}, fetched {fetched}", flush=True)
        for circuit, make in DEMOS.items():
            qc = make()
            locked, conf = lock(qc), None  # fresh lock per circuit, shared by its 5 compilers
            for r in detection_matrix(qc, backend, locked=locked):
                full = run(qc, backend, r["mode"], evidence=False, locked=locked, conf=conf)
                conf = full["confidentiality"]
                rows.append({"device": name, "calibration_utc": calibrated, "fetched_utc": fetched,
                             "circuit": circuit.split(" ")[0], "naive_tvd": full["naive"]["tvd"],
                             "esp_ratio": full["fidelity"]["ratio"], **r})
                print(f"   {rows[-1]['circuit']:<7}{r['mode']:<16}ESP ratio {rows[-1]['esp_ratio']:<7}{r['verdict']}",
                      flush=True)
    with CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
