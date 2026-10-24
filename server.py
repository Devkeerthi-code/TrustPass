"""TrustPass web UI: serves the site (index.html + web/ + assets/) and a small JSON API over the real pipeline.

  python server.py            -> http://localhost:8600
  python server.py --export   -> web/snapshot.json (every configuration, for a static host)
"""
import json
import sys
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
from qiskit_ibm_runtime import fake_provider

from circuits import DEMOS, VARIANTS
from compilers import COMPILERS
from lock import lock
from pipeline import detection_matrix, run
from score import confidentiality, secret_blind, view
from verify import FIDELITY_RATIO, NAIVE_TOL

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


META = {"circuits": {k: {"name": v, "kind": DEMOS[v]().metadata["kind"]} for k, v in CIRCUITS.items()},
        "modes": list(COMPILERS), "backends": list(BACKENDS)}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)  # index.html at the root, like GitHub Pages

    def do_GET(self):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return super().do_GET()
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            cid, mode, be = q.get("circuit", "grover"), q.get("mode", "honest"), q.get("backend", BACKENDS[0])
            decoys, seed = int(q.get("decoys", 0)), int(q.get("seed", 7))
            if cid not in CIRCUITS or mode not in COMPILERS or be not in BACKENDS or not 0 <= decoys <= 3:
                raise ValueError("unknown circuit, mode, backend or decoys")
            body = {"/api/meta": lambda: META,
                    "/api/run": lambda: run_json(cid, mode, be, decoys, seed),
                    "/api/matrix": lambda: matrix_json(cid, be, decoys, seed)}[url.path]()
            self.send(200, body)
        except (KeyError, ValueError) as e:
            self.send(400, {"error": str(e)})

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


if __name__ == "__main__":
    if "--export" in sys.argv:
        export()
    else:
        port = 8600
        print(f"TrustPass UI on http://localhost:{port}")
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
