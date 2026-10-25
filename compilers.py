"""Stand-ins for an untrusted third-party compiler (transpiler plugin, Qiskit Function, cloud stack).

Every mode gets the *locked* circuit and returns a compiled one. The malicious modes
tamper with the honest result in ways taken from the literature: a visible Trojan, a
Trojan small enough to hide in hardware noise, an input-triggered (dormant) Trojan
(John et al. 2025), and a saboteur that stays logically equivalent but parks the circuit
on the worst qubits and pads it with self-cancelling gates.
"""
import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import CircuitInstruction
from qiskit.circuit.library import RZGate, XGate

MASK_ANGLE = 0.35  # rad: shifts the output by a few percent, i.e. less than typical hardware noise


def honest(circ, backend, seed=7):
    return transpile(circ, backend, optimization_level=3, seed_transpiler=seed)


def _data_qubits(compiled):
    return compiled.layout.initial_index_layout(filter_ancillas=True)


def _two_qubit_gate(backend):
    return next(n for n in ("cz", "ecr", "cx") if n in backend.target.operation_names)


def _on_physical(gadget, qubits, backend):
    """Express a small gadget in the backend's native gates on fixed physical qubits."""
    return transpile(gadget, backend, initial_layout=qubits, optimization_level=0)


def trojan_overt(circ, backend, seed=7):
    """Flip one output bit right before measurement. Any output test sees it."""
    out = honest(circ, backend, seed)
    q = out.qubits[out.layout.final_index_layout()[0]]
    first_measure = next(i for i, inst in enumerate(out.data) if inst.operation.name == "measure")
    out.data.insert(first_measure, CircuitInstruction(XGate(), [q]))
    return out


def trojan_masked(circ, backend, seed=7):
    """A small phase kick mid-circuit: shifts results by less than hardware noise."""
    out = honest(circ, backend, seed)
    q = out.qubits[_data_qubits(out)[0]]
    mid = len(out.data) // 2
    out.data.insert(mid, CircuitInstruction(RZGate(MASK_ANGLE), [q]))
    return out


def trojan_dormant(circ, backend, seed=7):
    """Input-triggered Trojan: a CX at time zero between two data qubits.

    It does nothing on the standard |0...0> input, so every |0>-input test passes,
    but it fires whenever the circuit runs on a different input (e.g. as a subroutine).
    """
    out = honest(circ, backend, seed)
    cmap = backend.target.build_coupling_map()
    data = _data_qubits(out)
    # Prefer a coupled pair of data qubits so the gadget is one native 2q gate.
    pair = next(([a, b] for a in data for b in data if a != b and cmap.graph.has_edge(a, b)), data[:2])
    gadget = QuantumCircuit(2)
    gadget.cx(0, 1)
    g = _on_physical(gadget, pair, backend)
    tampered = out.copy()
    tampered.compose(g, front=True, inplace=True)
    return tampered


BROKEN = 0.5  # a stealthy saboteur skips dead qubits/couplers: garbage output would give it away


def worst_region(backend, n, percentile=0.9):
    """A connected set of n working physical qubits at the given error percentile.

    percentile=1.0 is the very worst region; ~0.9 is 'bad but plausible', which is what a
    saboteur who wants to stay unnoticed would pick.
    """
    t = backend.target
    two_q = _two_qubit_gate(backend)
    err = {e: (t[two_q][e].error or 0.0) for e in t[two_q] if t[two_q][e]}
    ok_edges = {e for e, v in err.items() if v < BROKEN}
    bad = {}
    for q in range(t.num_qubits):
        ro = t["measure"][(q,)].error or 0.0
        mine = [err[e] for e in ok_edges if q in e]
        if mine and ro < BROKEN:
            bad[q] = ro + float(np.mean(mine))
    nbrs = {q: {b if a == q else a for a, b in ok_edges if q in (a, b)} & bad.keys() for q in bad}
    target = float(np.quantile(list(bad.values()), percentile))
    closeness = lambda q: abs(bad[q] - target)
    for start in sorted(bad, key=closeness):  # fall back to the next candidate if it's an island
        region = [start]
        while len(region) < n:
            frontier = {nb for q in region for nb in nbrs[q]} - set(region)
            if not frontier:
                break
            region.append(min(frontier, key=closeness))
        if len(region) == n:
            return region
    raise ValueError("no connected working region of that size")


def saboteur(circ, backend, seed=7, pad_pairs=2, percentile=0.9):
    """Logically equivalent, deliberately bad: poor qubits plus self-cancelling gate pairs."""
    out = transpile(circ, backend, optimization_level=3, seed_transpiler=seed,
                    initial_layout=worst_region(backend, circ.num_qubits, percentile))
    two_q = _two_qubit_gate(backend)
    cmap = backend.target.build_coupling_map()
    data = _data_qubits(out)
    edges = [(a, b) for a in data for b in data if cmap.graph.has_edge(a, b)] or [tuple(data[:2])]
    pad = QuantumCircuit(out.num_qubits)
    for i in range(pad_pairs):
        a, b = edges[i % len(edges)]
        getattr(pad, two_q)(a, b)
        getattr(pad, two_q)(a, b)  # cz, ecr and cx are all self-inverse
    tampered = out.copy()
    tampered.compose(pad, front=True, inplace=True)
    return tampered


PLANT_GATES = ("x", "z", "s", "rz", "cx")
PLANT_POSITIONS = ("start", "middle", "end")


def plant(compiled, backend, gate, qubit, pos):
    """Your own Trojan: one gate on data qubit `qubit` of a compile, at the start, middle or end.

    start/middle use the qubit's initial placement, end its final one (right before measurement).
    cx targets the first other data qubit coupled to it. rz uses MASK_ANGLE. Bad input -> ValueError.
    Returns the tampered circuit and the physical qubits it touched.
    """
    if gate not in PLANT_GATES or pos not in PLANT_POSITIONS:
        raise ValueError(f"gate must be one of {PLANT_GATES} and pos one of {PLANT_POSITIONS}")
    data = compiled.layout.final_index_layout() if pos == "end" else _data_qubits(compiled)
    if not 0 <= qubit < len(data):
        raise ValueError(f"qubit must be 0-{len(data) - 1}")
    qubits = [data[qubit]]
    if gate == "cx":
        cmap = backend.target.build_coupling_map()
        partner = next((b for b in data if b != data[qubit] and cmap.graph.has_edge(data[qubit], b)), None)
        if partner is None:
            raise ValueError(f"data qubit {qubit} has no coupled data-qubit neighbour for cx")
        qubits.append(partner)
    gadget = QuantumCircuit(len(qubits))
    getattr(gadget, gate)(*([MASK_ANGLE] if gate == "rz" else []), *range(len(qubits)))
    g = _on_physical(gadget, qubits, backend)
    at = {"start": 0, "middle": len(compiled.data) // 2,
          "end": next(i for i, inst in enumerate(compiled.data) if inst.operation.name == "measure")}[pos]
    out = compiled.copy()
    for k, inst in enumerate(g.data):
        out.data.insert(at + k, inst.replace(qubits=[out.qubits[g.find_bit(q).index] for q in inst.qubits]))
    return out, qubits


COMPILERS = {
    "honest": honest,
    "trojan-overt": trojan_overt,
    "trojan-masked": trojan_masked,
    "trojan-dormant": trojan_dormant,
    "saboteur": saboteur,
}
