"""IBM's own published device data for our run dates: what success would it predict for each circuit?

For every completed hardware job (the same files as bench/compare.py), read back the exact circuits
it submitted (IBM job inputs; no new job, no QPU time) and IBM's published calibration of that
device at the job's calibration time (backend.properties(datetime=...), IBM's calibration archive).
Two expected-success estimates per circuit, each the product of (1 - error) over every CZ, SX/X and
measurement in the submitted circuit (RZ is virtual and free; idle time is not counted):
  median: every gate and readout charged the device-wide published median, so the estimate sees the
          gate count but not which qubits were used (independent of the audit's per-qubit ESP);
  qubits: the published per-qubit and per-pair values of the qubits the circuit actually used (the
          same kind of data the audit's ESP reads, here from IBM's archive for that date).
Both are the probability that no error occurs, a lower bound in spirit for the measured 1-TVD
(an error does not always move the histogram away from the ideal). Grover P(101) and the QAOA
approximation ratio are computed from the measured counts for bench/attested_literature.csv.
Writes bench/attested_device.csv.
    python bench/attested_device.py
"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qiskit_ibm_runtime import QiskitRuntimeService

from compare import load
from confidence import circuits, done, jobs

CSV = ROOT / "bench" / "attested_device.csv"
EDGES, MAXCUT = ((0, 1), (1, 2), (2, 3), (3, 0), (0, 2)), 4  # circuits.qaoa_maxcut's graph
FIELDS = ["run", "device", "job_id", "calibration_utc", "circuit", "mode", "verdict",
          "median_cz_error", "median_sx_error", "median_readout_error", "median_t1_us", "median_t2_us",
          "n_cz", "n_1q", "n_meas", "estimate_median", "estimate_qubits",
          "measured_one_minus_tvd", "measured_ratio", "estimate_median_ratio", "estimate_qubits_ratio",
          "p_secret_measured", "p_secret_ideal", "approx_ratio_measured", "approx_ratio_ideal"]


def medians(props):
    """Device-wide published medians from one calibration snapshot."""
    gate = lambda name: median(g.parameters[0].value for g in props.gates
                               if g.gate == name and g.parameters[0].name == "gate_error")
    qubit = lambda name: median(props.qubit_property(q)[name][0] for q in range(len(props.qubits))
                                if name in props.qubit_property(q))
    return {"median_cz_error": gate("cz"), "median_sx_error": gate("sx"),
            "median_readout_error": qubit("readout_error"),
            "median_t1_us": qubit("T1") * 1e6, "median_t2_us": qubit("T2") * 1e6}


def estimates(circ, props, med):
    """(n_cz, n_1q, n_meas, estimate with device medians, estimate with the used qubits' values)."""
    n = {"cz": 0, "1q": 0, "meas": 0}
    e_med = e_q = 1.0
    for inst in circ.data:
        name, qs = inst.operation.name, [circ.find_bit(q).index for q in inst.qubits]
        if name == "cz":
            n["cz"] += 1
            e_med *= 1 - med["median_cz_error"]
            e_q *= 1 - props.gate_error("cz", qs)
        elif name in ("sx", "x"):
            n["1q"] += 1
            e_med *= 1 - med["median_sx_error"]
            e_q *= 1 - props.gate_error(name, qs)
        elif name == "measure":
            n["meas"] += 1
            e_med *= 1 - med["median_readout_error"]
            e_q *= 1 - props.readout_error(qs[0])
        elif name not in ("rz", "barrier", "delay", "id"):
            raise ValueError(f"unexpected op {name} in a submitted circuit")
    return n["cz"], n["1q"], n["meas"], e_med, e_q


def cut_ratio(dist):
    """Expected cut / maximum cut over a distribution of 4-bit strings (bit i = qubit i, right to left)."""
    total = sum(dist.values())
    cut = lambda s: sum(s[-1 - a] != s[-1 - b] for a, b in EDGES)
    return sum(v * cut(k.replace(" ", "")) for k, v in dist.items()) / total / MAXCUT


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    service = QiskitRuntimeService()
    measured = {(r["job_id"], r["circuit"], r["mode"]): r for r in load()}
    run_of = {k[0]: r for k, r in measured.items()}
    rows, snapshots = [], {}
    for d in jobs():
        if not done(d):
            continue
        when = d.get("calibration_utc") or d["submitted_utc"]  # run 1 saved no calibration time
        key = (d["device"], when)
        if key not in snapshots:
            props = service.backend(d["device"]).properties(datetime=datetime.fromisoformat(when))
            snapshots[key] = (props, medians(props), props.last_update_date.astimezone(timezone.utc).isoformat(timespec="seconds"))
        props, med, calibrated = snapshots[key]
        pubs = service.job(d["job_id"]).inputs["pubs"]
        for k, (name, mode, counts, ideal) in enumerate(circuits(d)):
            circ = pubs[k][0] if isinstance(pubs[k], (tuple, list)) else pubs[k].circuit
            m = measured[(d["job_id"], name.split(" ")[0], mode)]
            n_cz, n_1q, n_meas, e_med, e_q = estimates(circ, props, med)
            row = {"run": run_of[d["job_id"]]["run"], "device": d["device"], "job_id": d["job_id"],
                   "calibration_utc": calibrated, "circuit": name.split(" ")[0], "mode": mode,
                   "verdict": m["verdict"], **{k2: round(v, 6) for k2, v in med.items()},
                   "n_cz": n_cz, "n_1q": n_1q, "n_meas": n_meas,
                   "estimate_median": round(e_med, 4), "estimate_qubits": round(e_q, 4),
                   "measured_one_minus_tvd": m["measured_one_minus_tvd"], "measured_ratio": m["measured_ratio"]}
            shots = sum(counts.values())
            if name.startswith("Grover"):
                row["p_secret_measured"] = round(counts.get("101", 0) / shots, 4)
                row["p_secret_ideal"] = round(ideal.get("101", 0) / sum(ideal.values()), 4)
            if name.startswith("QAOA"):
                row["approx_ratio_measured"] = round(cut_ratio(counts), 4)
                row["approx_ratio_ideal"] = round(cut_ratio(ideal), 4)
            rows.append(row)
    for r in rows:  # honest compile of the same lock on the same job = 1
        h = next(x for x in rows if x["job_id"] == r["job_id"] and x["circuit"] == r["circuit"] and x["mode"] == "honest")
        r["estimate_median_ratio"] = round(r["estimate_median"] / h["estimate_median"], 3)
        r["estimate_qubits_ratio"] = round(r["estimate_qubits"] / h["estimate_qubits"], 3)
    rows.sort(key=lambda r: (r["run"], r["circuit"], r["mode"] != "honest", r["mode"]))
    with CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {CSV.relative_to(ROOT)}: {len(rows)} circuits, {len(snapshots)} calibration snapshots")


if __name__ == "__main__":
    main()
