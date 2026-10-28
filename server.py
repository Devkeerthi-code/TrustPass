"""TrustPass web UI: serves the site (index.html + web/ + assets/) and a small JSON API over the real pipeline.

  python server.py            -> http://localhost:8600
  python server.py --export   -> web/snapshot.json (every configuration, for a static host) and web/plant.json
  python server.py --export-plant   -> only web/plant.json (every planted Trojan on FakeBrisbane)
"""
import json
import sys
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
from qiskit.quantum_info import Statevector
from qiskit_aer import AerSimulator
from qiskit_ibm_runtime import SamplerV2, fake_provider

from circuits import DEMOS, VARIANTS
from compilers import COMPILERS, MASK_ANGLE, PLANT_GATES, PLANT_POSITIONS, honest, plant
from lock import lock, unlock
from pipeline import detection_matrix, run
from score import confidentiality, secret_blind, view
from verify import FIDELITY_RATIO, NAIVE_TOL, audit_fidelity, check_function, naive_check, recheck, tvd

ROOT = Path(__file__).parent
WEB = ROOT / "web"
CIRCUITS = dict(zip(("grover", "qaoa", "vqe"), DEMOS))  # url id -> demo name
BACKENDS = ("FakeBrisbane", "FakeTorino")
HEAVY = threading.Lock()  # one pipeline at a time: concurrent native Qiskit/Aer work hung under load
_cache, _runs = {}, [0]


def cached(key, make):
    if key not in _cache:
        _cache[key] = make()
    return _cache[key]


def backend(name):
    return cached(("backend", name), lambda: getattr(fake_provider, name)())


def timeline(circ, merge=False, wires=None):
    """The circuit as columns for the trace display.

    merge=True folds every run of single-qubit gates on a wire into one block, which is
    how the locked circuit reads (one keyed block per segment) and keeps compiled circuits legible.
    """
    wires = wires or list(range(circ.num_qubits))
    row = {q: i for i, q in enumerate(wires)}
    level, cols, run1q = [0] * len(wires), [], {}

    def place(el, rows):
        span = range(min(rows), max(rows) + 1)
        c = max(level[r] for r in span)
        while len(cols) <= c:
            cols.append([])
        cols[c].append(el)
        for r in span:
            level[r] = c + 1

    def flush(r):
        if r in run1q:
            el = run1q.pop(r)
            place(el, [r])

    for inst in circ.data:
        name = inst.operation.name
        qs = [row[circ.find_bit(q).index] for q in inst.qubits if circ.find_bit(q).index in row]
        if name in ("barrier", "delay") or not qs:
            continue
        if name == "measure":
            flush(qs[0])
            place({"t": "meas", "q": qs}, qs)
        elif len(qs) == 1:
            params = [p for p in inst.operation.params]
            sym = [str(p) for p in params if hasattr(p, "parameters")]
            if merge:
                el = run1q.setdefault(qs[0], {"t": "block", "q": qs, "keys": [], "n": 0})
                el["n"] += 1
                el["keys"] += sym
            else:
                label = name.upper() + (f"({float(params[0]):.2f})" if params and not sym else "")
                place({"t": "gate", "q": qs, "label": label}, qs)
        else:
            for r in qs:
                flush(r)
            label = name.upper() + (f"({float(inst.operation.params[0]):.2f})"
                                    if inst.operation.params and not hasattr(inst.operation.params[0], "parameters") else "")
            place({"t": "multi", "q": qs, "label": label}, qs)
    for r in list(run1q):
        flush(r)
    return {"wires": [f"q{w}" for w in wires], "cols": cols}


def active(circ):
    return sorted({circ.find_bit(q).index for inst in circ.data for q in inst.qubits
                   if inst.operation.name not in ("barrier", "delay")})


def top(hist, keys):
    shots = sum(hist.values())
    return {k: round(hist.get(k, 0) / shots, 4) for k in keys}


def prepared(cid, decoys):
    def make():
        circuit = DEMOS[CIRCUITS[cid]]()
        locked = lock(circuit, decoys=decoys)
        variants = VARIANTS[CIRCUITS[cid]]()
        blind = {"raw": len({view(v) for v in variants}), "total": len(variants), "same": secret_blind(variants)}
        return circuit, locked, confidentiality(circuit, locked), blind
    return cached(("lock", cid, decoys), make)


def reason(r):
    fn, fd = r["functional"], r["fidelity"]
    if r["trust"]["verdict"] == "ACCEPT":
        return "Equivalent to your circuit and as good as an honest compile. Safe to run."
    if fd.get("verdict") == "not_native":
        return "Contains gates the device cannot run (unknown gate or uncoupled qubit pair)."
    if fn["passed"]:
        return (f"Equivalent, but sabotaged: placed on qubits with {fd['readout_err_used']:.1%} readout error "
                f"vs {fd['readout_err_device_median']:.1%} device median.")
    return {"not_equivalent": "Not equivalent to your circuit: the compiler changed what it computes.",
            "outputs_changed": "A measured output was dropped or re-routed."}.get(
        fn["verdict"], f"Contains instructions the verifier cannot prove safe ({fn['verdict']}).")


def run_json(cid, mode, backend_name, decoys=0, seed=7):
    circuit, locked, conf, blind = prepared(cid, decoys)
    be = backend(backend_name)
    with HEAVY:
        r = run(circuit, be, mode, decoys, seed, locked=locked, conf=conf)
    _runs[0] += 1
    final = r["circuits"]["final"]
    hist = r["histograms"]
    keys = sorted(hist["ideal"], key=hist["ideal"].get, reverse=True)[:8]
    ro = [be.target["measure"][(q,)].error or 0.0 for q in range(be.num_qubits)]
    return {
        "run": _runs[0], "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "circuit": {"id": cid, "name": CIRCUITS[cid], "kind": circuit.metadata["kind"],
                    "secret": circuit.metadata["secret"], "qubits": circuit.num_qubits},
        "backend": {"name": backend_name, "qubits": be.num_qubits, "median_readout": round(float(np.median(ro)), 4)},
        "mode": mode, "seed": seed, "decoys": decoys,
        "verdict": r["trust"]["verdict"], "reason": reason(r),
        "checks": {"naive": {**r["naive"], "tol": NAIVE_TOL},
                   "equivalence": r["functional"],
                   "fidelity": {**r["fidelity"], "threshold": FIDELITY_RATIO}},
        "confidentiality": conf, "blind": blind, "overhead": r["overhead"], "pillars": r["trust"],
        "evidence": {"fidelity": r["noisy_fidelity"], "outcomes": keys,
                     "ideal": top(hist["ideal"], keys), "returned": top(hist["returned"], keys),
                     "baseline": top(hist["baseline"], keys)},
        "views": {"original": timeline(circuit), "locked": timeline(locked.circuit, merge=True),
                  "final": timeline(final, merge=True, wires=active(final))},
        "stats": {w: {"ops": c.size(), "depth": c.depth(),
                      "twoq": sum(len(i.qubits) == 2 for i in c.data if i.operation.name != "barrier")}
                  for w, c in r["circuits"].items()},
    }


def matrix_json(cid, backend_name, decoys=0, seed=7):
    circuit, locked, _, _ = prepared(cid, decoys)  # the panel's lock, so the matrix agrees with CH1-CH3
    with HEAVY:
        return detection_matrix(circuit, backend(backend_name), decoys, seed, locked=locked)


def plant_json(cid, backend_name, gate, qubit, pos, decoys=0, seed=7):
    """One gate planted into the honest compile of the panel's lock, then the same three checks as /api/run."""
    circuit, locked, _, _ = prepared(cid, decoys)
    be = backend(backend_name)
    with HEAVY:
        compiled = honest(locked.circuit, be, seed=seed)
        tampered, physical = plant(compiled, be, gate, qubit, pos)  # ValueError on bad input -> 400
        final, baseline = unlock(tampered, locked.key), unlock(compiled, locked.key)
        r = {"naive": naive_check(circuit, final), "functional": check_function(circuit, final),
             "fidelity": audit_fidelity(final, be, baseline)}
    r["trust"] = {"verdict": "ACCEPT" if r["functional"]["passed"] and r["fidelity"]["passed"] else "REJECT"}
    return {"circuit": {"id": cid, "name": CIRCUITS[cid], "qubits": circuit.num_qubits},
            "backend": {"name": backend_name},
            "planted": {"gate": gate, "qubit": qubit, "pos": pos, "physical": physical,
                        "angle": MASK_ANGLE if gate == "rz" else None},
            "verdict": r["trust"]["verdict"], "reason": reason(r),
            "checks": {"naive": {**r["naive"], "tol": NAIVE_TOL}, "equivalence": r["functional"],
                       "fidelity": {**r["fidelity"], "threshold": FIDELITY_RATIO}}}


def plant_args(q):
    """gate, qubit, pos of a planted Trojan from a query, or ValueError (plant() checks the qubit range)."""
    if q.get("gate") not in PLANT_GATES or q.get("pos") not in PLANT_POSITIONS or not q.get("qubit", "").isdigit():
        raise ValueError(f"gate must be one of {', '.join(PLANT_GATES)}, pos one of"
                         f" {', '.join(PLANT_POSITIONS)}, qubit a data-qubit index")
    return q["gate"], int(q["qubit"]), q["pos"]


# ---------- real IBM hardware: only with --allow-ibm, one job in flight, a hard budget ----------
IBM_DEVICES = ("ibm_fez", "ibm_kingston", "ibm_marrakesh")
IBM_MODES = (*COMPILERS, "plant")
IBM_SHOTS, IBM_MAX_SUBMITS, IBM_MIN_SECONDS = 2000, 6, 120
IBM_WORKLOADS = "https://quantum.cloud.ibm.com/workloads"  # qiskit-ibm-runtime exposes no per-job URL
LIVE_IBM = ROOT / "bench" / "live_ibm"
IBM = {"allowed": False, "busy": False, "job": None, "submits": 0}
IBM_STATE = threading.Lock()


def ibm_service():
    from qiskit_ibm_runtime import QiskitRuntimeService
    return cached("ibm-service", QiskitRuntimeService)  # the saved account; the token is never read here


def ibm_device(q):
    name = q.get("backend", "")
    if name not in IBM_DEVICES:
        raise ValueError(f"backend must be one of {', '.join(IBM_DEVICES)}")
    return name


def submit_args(q):
    """Strict: circuit, mode, backend, and gate/qubit/pos only (and always) for mode=plant."""
    planted = q.get("mode") == "plant"
    allowed = {"circuit", "mode", "backend"} | ({"gate", "qubit", "pos"} if planted else set())
    if set(q) - allowed or q.get("circuit") not in CIRCUITS or q.get("mode") not in IBM_MODES:
        raise ValueError(f"needs circuit ({', '.join(CIRCUITS)}), mode ({', '.join(IBM_MODES)}) and backend;"
                         " gate, qubit and pos only with mode=plant")
    args = {"circuit": q["circuit"], "mode": q["mode"], "backend": ibm_device(q)}
    if planted:
        args["gate"], args["qubit"], args["pos"] = plant_args(q)
        if args["qubit"] >= DEMOS[CIRCUITS[args["circuit"]]]().num_qubits:
            raise ValueError("qubit is not a data qubit of this circuit")
    return args


def calibrated(be):
    return be.properties(refresh=True).last_update_date.astimezone(timezone.utc).isoformat(timespec="seconds")


def ibm_status(name):
    service = ibm_service()
    be = cached(("ibm", name), lambda: service.backend(name))
    st, usage = be.status(), service.usage()
    return {"device": name, "operational": bool(st.operational), "status_msg": st.status_msg,
            "pending_jobs": st.pending_jobs, "remaining_seconds": usage.get("usage_remaining_seconds"),
            "min_seconds": IBM_MIN_SECONDS, "calibration_utc": calibrated(be),
            "submits_left": IBM_MAX_SUBMITS - IBM["submits"],
            "in_flight": bool(IBM["busy"] or (IBM["job"] and job_open()))}


def ideal(circ):
    """Exact output distribution of the original circuit (no sampling noise in the reference)."""
    probs = Statevector(circ.remove_final_measurements(inplace=False)).probabilities_dict()
    return {k: round(float(v), 6) for k, v in probs.items() if v > 1e-9}


def ibm_sample(be, circuits):
    """The only place a job is submitted: one SamplerV2 job of exactly 2 circuits x IBM_SHOTS."""
    if len(circuits) != 2:
        raise ValueError(f"refusing to submit {len(circuits)} circuits: exactly 2 per job")
    return SamplerV2(mode=be).run(circuits, shots=IBM_SHOTS)


class Refused(Exception):
    """A guard said no (409): nothing was submitted."""


def ibm_submit(args, seed=7):
    """One fresh lock; the judge's compile and an honest baseline of it; verify on the live target;
    re-audit on the newest calibration; then one 2-circuit job. Returns without waiting for it."""
    service = ibm_service()
    be = cached(("ibm", args["backend"]), lambda: service.backend(args["backend"]))
    left = service.usage().get("usage_remaining_seconds")
    if left is not None and left < IBM_MIN_SECONDS:
        raise Refused(f"quota low: {left:.0f} s of QPU time left (needs {IBM_MIN_SECONDS})")
    circuit = DEMOS[CIRCUITS[args["circuit"]]]()
    with HEAVY:
        be.refresh()  # the device's live target
        locked = lock(circuit)  # fresh, OS entropy
        compiled = honest(locked.circuit, be, seed=seed)
        baseline, physical = unlock(compiled, locked.key), None
        if args["mode"] == "plant":
            tampered, physical = plant(compiled, be, args["gate"], args["qubit"], args["pos"])
            final = unlock(tampered, locked.key)
        else:
            final = unlock(COMPILERS[args["mode"]](locked.circuit, be, seed=seed), locked.key)
        r = {"naive": naive_check(circuit, final), "functional": check_function(circuit, final),
             "fidelity": audit_fidelity(final, be, baseline)}
        r["trust"] = {"verdict": "ACCEPT" if r["functional"]["passed"] and r["fidelity"]["passed"] else "REJECT"}
        ref, sim = ideal(circuit), AerSimulator.from_backend(be)  # today's noise model, not a cached one
        predicted = {k: round(1 - tvd(ref, sim.run(c, shots=IBM_SHOTS, seed_simulator=1).result().get_counts()), 4)
                     for k, c in (("judge", final), ("baseline", baseline))}
        cal = calibrated(be)
        again = recheck(final, baseline, be)  # time of use: the calibration may have moved
    if r["fidelity"]["passed"] and not again["passed"]:
        raise Refused(f"calibration moved: the fidelity audit now fails (ESP ratio {r['fidelity']['ratio']}"
                      f" -> {again['ratio']}); nothing was submitted")
    queued = be.status().pending_jobs
    job = ibm_sample(be, [final, baseline])
    jid = job.job_id()
    record = {"job_id": jid, "device": args["backend"], "submitted_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "calibration_utc": cal, "queue_at_submit": queued, "remaining_seconds_at_submit": left,
              "shots": IBM_SHOTS, "transpiler_seed": seed, "naive_tol": NAIVE_TOL, "fidelity_threshold": FIDELITY_RATIO,
              "params": args, "planted_physical": physical, "circuits": ["judge", "baseline"],
              "secret": circuit.metadata["secret"], "verdict": r["trust"]["verdict"], "reason": reason(r),
              "checks": {"naive": r["naive"], "equivalence": r["functional"], "fidelity": r["fidelity"],
                         "recheck": again},
              "predicted_one_minus_tvd": predicted, "ideal": ref, "url": IBM_WORKLOADS}
    LIVE_IBM.mkdir(parents=True, exist_ok=True)
    (LIVE_IBM / f"{jid}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


STATUS = {"INITIALIZING": "queued", "QUEUED": "queued", "RUNNING": "running", "DONE": "done",
          "ERROR": "error", "CANCELLED": "error"}


def ibm_job(jid):
    """Status of a job this panel submitted; when done, the measured results (saved with the record)."""
    path = LIVE_IBM / f"{jid}.json"
    if not (jid.isalnum() and path.is_file()):
        raise ValueError("unknown job id (only jobs submitted from this panel)")
    rec = json.loads(path.read_text(encoding="utf-8"))
    if "results" in rec:
        return {**rec, "status": "done"}
    job = ibm_service().job(jid)
    status = STATUS.get(job.status(), "queued")
    if status == "error":
        rec.update(status="error", error=job.error_message())
    if status == "done":
        out = {}
        for name, res in zip(rec["circuits"], job.result()):
            got = res.join_data().get_counts()
            d = tvd(rec["ideal"], got)
            out[name] = {"counts": got, "one_minus_tvd": round(1 - d, 4), "naive_tvd": round(d, 4),
                         "naive_passed": d < NAIVE_TOL,
                         "p_secret": round(got.get(rec["secret"], 0) / rec["shots"], 4)
                         if isinstance(rec["secret"], str) else None}
        out["measured_ratio"] = round(out["judge"]["one_minus_tvd"] / out["baseline"]["one_minus_tvd"], 3)
        stamps = job.metrics().get("timestamps", {})
        if stamps.get("created") and stamps.get("running"):
            t = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
            rec["queue_seconds"] = round((t(stamps["running"]) - t(stamps["created"])).total_seconds())
        rec.update(results=out, timestamps=stamps, qpu_seconds=job.usage(),
                   finished_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if status in ("done", "error"):
        path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        with IBM_STATE:
            if IBM["job"] == jid:
                IBM["job"] = None
    return {**rec, "status": status}


def job_open():
    """Is the last submitted job still queued or running? (Asks IBM; a finished one is cleared.)"""
    jid = IBM["job"]
    if jid and STATUS.get(ibm_service().job(jid).status(), "queued") in ("done", "error"):
        with IBM_STATE:
            if IBM["job"] == jid:
                IBM["job"] = None
        return None
    return jid


def ibm_route(path, q):
    """(status code, body) for /api/ibm/*."""
    if not IBM["allowed"]:
        return 403, {"error": "real-hardware runs are off: start the server with --allow-ibm"}
    if path == "/api/ibm/status":
        if set(q) - {"backend"}:
            raise ValueError("status takes only backend")
        return 200, ibm_status(ibm_device(q))
    if path == "/api/ibm/job":
        if set(q) != {"id"}:
            raise ValueError("job takes only id")
        return 200, ibm_job(q["id"])
    if path != "/api/ibm/submit":
        return 404, {"error": f"unknown endpoint {path}"}
    args = submit_args(q)
    with IBM_STATE:  # claim the single slot before any IBM call
        if IBM["submits"] >= IBM_MAX_SUBMITS:
            return 429, {"error": f"this server run already submitted {IBM_MAX_SUBMITS} jobs; restart it to submit more"}
        if IBM["busy"]:
            return 409, {"error": "a submission is already being prepared"}
        IBM["busy"] = True
    try:
        if IBM["job"] and job_open():
            return 409, {"error": f"job {IBM['job']} is still in flight; wait for it to finish"}
        try:
            rec = ibm_submit(args)
        except Refused as e:
            return 409, {"error": str(e)}
        with IBM_STATE:
            IBM["job"], IBM["submits"] = rec["job_id"], IBM["submits"] + 1
        return 200, {**rec, "submits_left": IBM_MAX_SUBMITS - IBM["submits"]}
    finally:
        IBM["busy"] = False


META = {"circuits":{k: {"name": v, "kind": DEMOS[v]().metadata["kind"]} for k, v in CIRCUITS.items()},
        "modes": list(COMPILERS), "backends": list(BACKENDS)}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)  # index.html at the root, like GitHub Pages

    def do_GET(self):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return super().do_GET()
        if url.path.startswith("/api/ibm/"):
            q = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
            try:
                return self.send(*ibm_route(url.path, q))
            except ValueError as e:  # bad parameters, or a planted gate that does not fit the compile
                return self.send(400, {"error": str(e)})
            except Exception as e:
                return self.send(500, {"error": f"{type(e).__name__}: {e}"})
        route = {"/api/meta": lambda: META,
                 "/api/run": lambda: run_json(cid, mode, be, decoys, seed),
                 "/api/matrix": lambda: matrix_json(cid, be, decoys, seed),
                 "/api/plant": lambda: plant_json(cid, be, q["gate"], int(q["qubit"]), q["pos"], decoys, seed)}.get(url.path)
        if route is None:
            return self.send(404, {"error": f"unknown endpoint {url.path}"})
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            cid, mode, be = q.get("circuit", "grover"), q.get("mode", "honest"), q.get("backend", BACKENDS[0])
            decoys, seed = int(q.get("decoys", 0)), int(q.get("seed", 7))
            if cid not in CIRCUITS or mode not in COMPILERS or be not in BACKENDS or not 0 <= decoys <= 3:
                raise ValueError("unknown circuit, mode, backend or decoys")
            if url.path == "/api/plant":
                plant_args(q)
        except ValueError as e:
            return self.send(400, {"error": str(e)})
        try:
            self.send(200, route())
        except Exception as e:  # never drop the connection: the UI shows the error instead
            bad = isinstance(e, ValueError) and url.path == "/api/plant"  # qubit out of range, or cx with no partner
            self.send(400 if bad else 500, {"error": str(e) if bad else f"{type(e).__name__}: {e}"})

    def send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def export():
    """Every configuration the UI offers at the default decoys/seed, for a static host."""
    snap = {"meta": META, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "runs": {}, "matrices": {}}
    for cid in CIRCUITS:
        for be in BACKENDS:
            snap["matrices"][f"{cid}|{be}"] = matrix_json(cid, be)
            for mode in COMPILERS:
                snap["runs"][f"{cid}|{mode}|{be}"] = run_json(cid, mode, be)
                print(f"{cid} {be} {mode}", flush=True)
    (WEB / "snapshot.json").write_text(json.dumps(snap))
    print(f"wrote {WEB / 'snapshot.json'}")
    export_plant()


def export_plant(be="FakeBrisbane"):
    """Every planted Trojan the UI offers, for a static host (FakeBrisbane only, at the default decoys/seed)."""
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "backend": be, "runs": {}}
    for cid in CIRCUITS:
        for gate in PLANT_GATES:
            for qubit in range(prepared(cid, 0)[0].num_qubits):
                for pos in PLANT_POSITIONS:
                    try:
                        r = plant_json(cid, be, gate, qubit, pos)
                        r = {k: r[k] for k in ("planted", "verdict", "reason", "checks")}
                    except ValueError as e:
                        r = {"error": str(e)}
                    out["runs"][f"{cid}|{gate}|{qubit}|{pos}"] = r
        print(f"plant {cid}", flush=True)
    (WEB / "plant.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {WEB / 'plant.json'}")


if __name__ == "__main__":
    if "--export" in sys.argv:
        export()
    elif "--export-plant" in sys.argv:
        export_plant()
    else:
        port = 8600
        IBM["allowed"] = "--allow-ibm" in sys.argv
        print(f"TrustPass UI on http://localhost:{port}"
              + (f" · real IBM hardware ON ({', '.join(IBM_DEVICES)}, at most {IBM_MAX_SUBMITS} jobs)" if IBM["allowed"] else ""))
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
