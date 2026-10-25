"""Calibration drift: re-audit the Grover compiles from the hardware runs on today's calibration.

The bench JSON files do not keep the lock key, so the compiles cannot be rebuilt from them. Instead
the exact circuits each job submitted are read back from IBM (job inputs; no new job, no QPU time).
For ibm_fez and ibm_kingston: fetch the current calibration, then score the honest and saboteur
Grover circuits of every completed run with the ESP audit, the honest one as the baseline as at
check time. Run numbers are those of bench/compare.py. Writes bench/drift.csv.
    python bench/drift.py
"""
import csv
import json
import sys
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qiskit_ibm_runtime import QiskitRuntimeService

from compare import load
from verify import audit_fidelity

DEVICES = ("ibm_fez", "ibm_kingston")
CSV = ROOT / "bench" / "drift.csv"
FIELDS = ["run", "device", "job_id", "mode", "calibration_then_utc", "calibration_now_utc",
          "esp_then", "esp_now", "esp_ratio_then", "esp_ratio_now", "audit_then", "audit_now", "source"]


def grover_runs():
    """(job file data, {mode: (index in the job, saved check)}) for every completed Grover run."""
    for path in sorted((ROOT / "bench").glob("ibm_*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        if d["device"] not in DEVICES:
            continue
        if "runs" in d:  # demo.py --ibm: honest then saboteur, in submission order
            yield d, {m: (i, r) for i, (m, r) in enumerate(d["runs"].items())}
        elif all("counts" in e for e in d["circuits"]):
            yield d, {e["mode"]: (i, e) for i, e in enumerate(d["circuits"])
                      if e["circuit"].startswith("Grover") and e["mode"] in ("honest", "saboteur")}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    service = QiskitRuntimeService()
    run_of = {r["job_id"]: r["run"] for r in load()}
    backends, rows = {}, []
    for d, picked in grover_runs():
        if d["device"] not in backends:
            b = service.backend(d["device"])
            backends[d["device"]] = (b, b.properties().last_update_date.astimezone(timezone.utc).isoformat(timespec="seconds"))
        backend, now = backends[d["device"]]
        pubs = service.job(d["job_id"]).inputs["pubs"]
        circ = {m: (pubs[i][0] if isinstance(pubs[i], (tuple, list)) else pubs[i].circuit) for m, (i, _) in picked.items()}
        for mode, (_, saved) in picked.items():
            a = audit_fidelity(circ[mode], backend, circ["honest"])
            rows.append({"run": run_of[d["job_id"]], "device": d["device"], "job_id": d["job_id"], "mode": mode,
                         "calibration_then_utc": d.get("calibration_utc", ""), "calibration_now_utc": now,
                         "esp_then": saved["esp"], "esp_now": a["esp"], "esp_ratio_then": saved["esp_ratio"],
                         "esp_ratio_now": a["ratio"], "audit_then": saved["audit"], "audit_now": a["verdict"],
                         "source": "exact submitted circuits (IBM job inputs)"})
            r = rows[-1]
            print(f"run {r['run']} {r['device']:<13}{mode:<9} calibration {r['calibration_then_utc'] or 'not saved'}"
                  f" -> {now}: ESP {r['esp_then']:.3f} -> {r['esp_now']:.3f},"
                  f" ratio {r['esp_ratio_then']:.3f} -> {r['esp_ratio_now']:.3f} ({r['audit_then']} -> {r['audit_now']})")
    rows.sort(key=lambda r: (r["run"], r["mode"] != "honest"))
    with CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
