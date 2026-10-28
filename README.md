# TrustPass

[![tests](https://github.com/Devkeerthi-code/TrustPass/actions/workflows/tests.yml/badge.svg)](https://github.com/Devkeerthi-code/TrustPass/actions/workflows/tests.yml)

**Zero-trust compilation for quantum circuits: lock the circuit before an untrusted compiler sees it, then check that what comes back is the same circuit and does not run measurably worse than a free local compile.**

![The TrustPass TP-1 front panel (static snapshot, Grover-3 on FakeBrisbane): SOURCE turns from Honest to Saboteur, and the lamp goes from green ACCEPT to red REJECT while the naive and equivalence channels still say PASS](docs/source-honest-to-saboteur.gif)

Q-HACK INDIA 2026 (IBM Qiskit Fall Fest), Quantum Security & Cryptography track. Round 1 prototype.

```bash
pip install -r requirements.txt   # Python 3.12; full setup under Quickstart below
python demo.py --matrix           # the detection matrix: which check catches which attack
python test_trustpass.py          # 11 checks
python server.py                  # the live instrument UI: http://localhost:8600
```

**Stack:** Qiskit 2.5 · Qiskit Aer · MQT QCEC 3.10 · IBM fake backends with real calibration data · hand-built HTML/CSS/JS UI.

**Try it in your browser: https://devkeerthi-code.github.io/TrustPass/** (a snapshot of real pipeline runs, nothing to install; run `python server.py` locally for live runs).

The interface is a bench instrument: put a circuit on the panel, turn **SOURCE** to pick the untrusted compiler, and read three channels. Every number on it comes from a real run of the pipeline below. Run it locally with `python server.py` (live runs), or open the static snapshot (`index.html` + `web/snapshot.json`, precomputed by the same pipeline) on any static host.

**Plant a Trojan.** Below the panel you can insert one gate of your own (X, Z, S, RZ(0.35) or CX, on any data qubit, at the start, in the middle or right before measurement) into the honest compile of the panel's lock, and the same three checks run on it (`/api/plant`). The static site reads `web/plant.json` instead: every combination for the 3 demos on FakeBrisbane, 165 in all, 12 of them a CX on a qubit with no coupled data-qubit neighbour, which is refused. In the other 153, QCEC returned `not_equivalent` and the verdict was REJECT every time, while the histogram test passed 86 of them and the fidelity audit all 153 (one extra gate barely moves ESP), so catching these is QCEC's job.

## The problem

The compiler is increasingly someone else's code, and the compiled circuit comes back to you before it runs:

- **Third-party transpiler plugins.** Through Qiskit's [plugin interface](https://quantum.cloud.ibm.com/docs/en/api/qiskit/transpiler_plugins), any pip package can supply the layout, routing, translation, optimization or synthesis stage of `transpile`. Malicious packages are a documented supply-chain problem: PyPI handled more than 2,000 malware reports in 2025 ([PyPI 2025 in review](https://blog.pypi.org/posts/2025-12-31-pypi-2025-in-review/)).
- **Remote compile services.** IBM's Qiskit Transpiler Service ([`TranspilerService`](https://quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-transpiler/transpiler-service-transpiler-service)) sends the circuit to a cloud endpoint and returns the transpiled circuit.

Platforms that both compile and run are a different case, for example full-stack clouds such as QpiAI's (built around India's 25-qubit [QpiAI-Indus](https://www.businesswire.com/news/home/20250415961497/en/QpiAI-Announces-Dawn-of-Quantum-Era-in-India-With-25-Qubit-Quantum-Computer)). If such a platform returns the compiled circuit before running it, TrustPass still checks integrity and fidelity, but it cannot keep the circuit secret from the party that runs it.

To our knowledge no real-world malicious quantum compiler has been publicly reported. An untrusted compiler is the threat model the research below assumes. The compiler sees the whole circuit, so it can:

1. **Steal it.** The circuit is the IP: a Grover oracle's marked item, a QAOA graph with its trained angles, a VQE ansatz with its trained weights.
2. **Plant a Trojan.** Add a gate that changes the answer, either small enough to hide in hardware noise or dormant until the circuit gets a non-|0...0⟩ input ([John et al.](https://arxiv.org/abs/2502.08880)).
3. **Sabotage fidelity.** Return a circuit that is logically equivalent but parked on the worst qubits and padded with self-cancelling gates. Every equivalence checker says "equivalent"; the results just get worse.

What most users do today is run the circuit on |0...0⟩ and eyeball the histogram. In our runs that check catches the overt Trojan but misses the dormant Trojan and the saboteur on every demo, and misses the masked Trojan on Grover every time (see the detection matrix below).

## Research gaps

| # | Work | What it shows | What TrustPass does about it |
|---|------|---------------|------------------------------|
| 1 | E-LoQ, Liu, John, Wang, IEEE HOST 2025 ([arXiv:2412.17101](https://arxiv.org/abs/2412.17101)) | Locking is evaluated for concealment only; nothing checks the circuit that comes back. | Locking plus a formal equivalence check and a fidelity audit of the returned circuit. |
| 2 | CLOAQ, Langford et al., ISCAS 2026 ([arXiv:2602.23569](https://arxiv.org/abs/2602.23569)) | Prior obfuscation was evaluated only with all-\|0⟩ inputs. | Wrong-key leakage is also measured on Haar-random input states; the equivalence check covers every input. |
| 3 | Zhang & Liu, "Security Evaluation of Quantum Circuit Split Compilation under an Oracle-Guided Attack" ([arXiv:2511.04842](https://arxiv.org/abs/2511.04842), Nov 2025) | A few input/output pairs recover split-compiled circuits; new schemes need security evaluation. | Measured, not defended: in our red team, the outputs of 6 inputs fit the whole key of a 2-qubit QAOA (see limitations). Out of our threat model, since the compiler never sees results; a defence is Round 2. |
| 4 | Rahman, Haghparast, Mikkonen, "On the Figures of Merit for Quantum Software Security: Toward a Benchmarking Rubric" ([arXiv:2608.05831](https://arxiv.org/abs/2608.05831), Aug 2026) | TVD/DFC metrics are ad hoc and incompatible across papers. | One fixed scorecard for every run: confidentiality, integrity, quality, cost. |
| 5 | John, Golla, Wang, "Quantum Trojan Insertion: Controlled Activation for Covert Circuit Manipulation" ([arXiv:2502.08880](https://arxiv.org/abs/2502.08880), 2025) | Trojans can stay dormant until a specific input triggers them. | A dormant Trojan is one of our attack modes; it passes the \|0⟩ test and is caught by the equivalence check. |
| 6 | Zheng, Shang, Tan, "A Dual-Mode Quantum Circuit Trojan Attack Detection Scheme Based on Unitary Matrix Features", CQCC 2025, Springer CCIS 2026 ([doi:10.1007/978-981-95-4791-3_6](https://doi.org/10.1007/978-981-95-4791-3_6)) | A CNN classifies circuits as Trojaned or clean from their unitary-matrix features: 91.6% accuracy on 1,550 benchmark circuits, so some circuits are misclassified. | Formal equivalence checking with [MQT QCEC](https://github.com/cda-tum/mqt-qcec) (Burgholzer & Wille): a proof for the circuit at hand, not a classifier with an error rate. In our scaling benchmark the proof finishes up to 10 qubits (QAOA) and times out at 14 (see Scaling). |
| 7 | MacNeil, Sunkavilli, Yu, "Authenticating Quantum Circuits Through Localized Noise Fingerprints", QSec '25 (ACM CCS workshop) ([doi:10.1145/3733825.3765283](https://doi.org/10.1145/3733825.3765283)) | Proposes, as a forward-looking concept, comparing a circuit's output distribution (TVD) on an untrusted quantum computer with a trusted noise fingerprint, using diagnostic ancilla qubits, to detect structural tampering such as gate reordering or injection. | Checks the returned circuit before it runs, with no extra qubits: QCEC for structural tampering, and an ESP audit for equivalence-preserving sabotage, in the same pipeline as locking. |
| 8 | Broadbent, Fitzsimons, Kashefi, "Universal Blind Quantum Computation", FOCS 2009 ([arXiv:0807.4154](https://arxiv.org/abs/0807.4154)) | Hides inputs, outputs and the computation from the server, but the client must prepare single qubits and run an interactive measurement-based protocol. | Works on today's circuit-model toolchains with no quantum client, and hides less: the CX skeleton stays visible (see limitations). |
| 9 | Saki, Suresh, Topaloglu, Ghosh, "Split Compilation for Security of Quantum Circuits", ICCAD 2021 ([doi:10.1109/ICCAD51958.2021.9643478](https://doi.org/10.1109/ICCAD51958.2021.9643478)) | Splits the circuit and sends the parts to several compilers, or to one compiler at different times, so no single compile sees all of it. | One compiler sees the whole locked circuit; the key keeps the angles secret, and the returned circuit is verified. Gap 3 is an attack on split compilation. |

To our knowledge, no prior tool combines locking, functional verification and a fidelity audit in one pipeline.

## How TrustPass works

Threat model: the compiler is untrusted, your machine is trusted. You bind the key and submit the final circuit to the hardware provider, a different party; the compiler never sees execution results.

```mermaid
flowchart LR
  subgraph trusted["Your machine (trusted)"]
    A["circuit"] --> L["lock"]
    U["unlock: bind key"] --> V["verify: QCEC + fidelity audit"] --> S["score + verdict"]
  end
  subgraph untrusted["Third party (untrusted)"]
    C["compile"]
  end
  L -- "locked circuit, angles replaced by key parameters" --> C
  C -- "compiled locked circuit" --> U
  S -- "ACCEPT" --> H["hardware provider"]
```

1. **Lock** (`lock.py`). The circuit is rewritten as CX gates plus exactly one keyed block per wire segment, `rz(k) sx rz(k') sx rz(k'')`. Every rz angle is a `Parameter`; the values are the key and never leave your machine. The CX skeleton is flattened too:
   - *Uniform pair counts.* Decoy `cx cx` pairs (the identity) are spliced into the gate stream at random positions and locked like any real gate, until every qubit pair carries the same number of CX gates. A real two-qubit interaction and a decoy both look like CX-block-CX, and counting CX per pair no longer reveals the interaction graph. `decoys=k` adds k extra padding rounds on top (default 0).
   - *Random CX direction.* Every CX is flipped with probability 1/2; the H⊗H that the flip needs is absorbed into the neighbouring keyed blocks, so it adds no gates to the locked circuit.
   - *Nothing else leaves.* The locked circuit is named `locked`, has empty metadata and global phase 0.
   - *Fresh randomness.* Decoy positions and CX directions come from OS entropy on every lock. The `seed` in `pipeline.py`, `demo.py` and the app only fixes the transpiler.

   Grover-3 becomes 153 key angles and 24 visible CX gates and needs no decoys (its 3 qubit pairs already carry 8 CX each). QAOA-4 needs 1 decoy pair, VQE-4 needs 3.
2. **Untrusted compile** (`compilers.py`). Five stand-in compilers, all of which only ever see the locked circuit: `honest` (Qiskit `transpile`, optimization level 3), `trojan-overt` (X before measurement), `trojan-masked` (rz(0.35) mid-circuit), `trojan-dormant` (CX at t=0 between two data qubits: a no-op on |0...0⟩), `saboteur` (qubits at the device's 90th error percentile, skipping broken ones, plus 2 self-cancelling two-qubit gate pairs).
3. **Unlock.** Bind the key into the compiled circuit, locally.
4. **Verify** (`verify.py`). Three checks:
   - *naive test*: what users do today. Ideal-simulator histogram on |0...0⟩, pass if TVD < 0.10.
   - *equivalence*: first, every classical bit must be measured from the same logical qubit as in the original (through the compiler's final layout); then MQT QCEC proves the returned circuit implements the same unitary (up to global phase) for every input. Delays are logically the identity, so QCEC checks a copy with them removed (the fidelity audit charges their idle time). Fails closed: anything else QCEC cannot handle (reset, feed-forward) is a REJECT.
   - *fidelity audit*: estimated success probability (ESP, the product of 1 - error over every gate and measurement, from the backend's calibration data) versus a free local honest compile of the same locked circuit. It rejects any compile measurably worse (ratio < 0.90) than a free local Qiskit compile, malicious or merely weak. It also fails closed: any gate the device cannot run on those qubits (an unknown gate, or a two-qubit gate on an uncoupled pair) is a REJECT whatever the ratio. If the returned circuit contains delays (a scheduled compile), idle time counts too: both it and the baseline are ALAP-scheduled locally (which adds nothing to a compile that is already ALAP-scheduled), and each scores ESP × ∏ exp(-t / min(T1, T2)) over every delay on a qubit the circuit uses, t the delay's duration and T1, T2 that qubit's calibrated times. Leading delays, where a qubit still sits in |0⟩, are charged too, so this is pessimistic on both sides alike. False rejects: 0 of 360 honest compiles (3 demos × FakeBrisbane and FakeTorino × optimization levels 1-3 × transpiler seeds 0-19, each against the pipeline's level-3, seed-7 baseline), ESP ratio 0.948-1.002.
5. **Score** (`score.py`). Confidentiality, integrity and quality pillars (0-100) and one verdict: ACCEPT only if both the equivalence check and the fidelity audit pass. Confidentiality is capped at 0 if the locked circuit carries metadata or its original name, and at 50 if qubit pairs carry different CX counts. Right before a job is submitted to real hardware, `verify.recheck` re-runs the fidelity audit on the device's newest calibration and refuses to submit a circuit that passed at check time but now fails ([Calibration drift](#calibration-drift)).

## The detection matrix

FakeBrisbane (127-qubit Eagle noise model, ECR basis), Grover-3 with marked item `101`, transpiler seed 7. Every lock is fresh randomness, so we ran the matrix with 15 different locks: the ✓/✗ pattern was identical every time; numbers are min-max.
✓ = the check passed the circuit, ✗ = the check rejected it.

| Compiler | Naive \|0⟩ test (TVD) | QCEC equivalence | Fidelity audit (ESP ratio) | Verdict |
|----------|----------------------|------------------|----------------------------|---------|
| honest | ✓ (0.003-0.004) | ✓ | ✓ (1.00) | ACCEPT |
| trojan-overt | ✗ (0.940-0.943) | ✗ | ✓ (1.00) | REJECT |
| trojan-masked | ✓ (0.016-0.017) | ✗ | ✓ (1.00) | REJECT |
| trojan-dormant | ✓ (0.003-0.004) | ✗ | ✓ (0.99) | REJECT |
| saboteur | ✓ (0.003-0.004) | ✓ | ✗ (0.54-0.55) | REJECT |

No single check catches everything: QCEC catches every Trojan but passes the saboteur (it really is equivalent); only the fidelity audit catches the saboteur.

Which checks caught each attack, all three demos, FakeBrisbane and FakeTorino (133-qubit Heron noise model, CZ basis), 15 locks per demo per backend:

| Compiler | Grover-3 | QAOA-4 | VQE-4 |
|----------|----------|--------|-------|
| honest | none, ACCEPT | none, ACCEPT | none, ACCEPT |
| trojan-overt | naive, QCEC | naive, QCEC | naive, QCEC |
| trojan-masked | QCEC | QCEC; naive too in 3 of 40 locks | QCEC; naive too in 20 of 40 locks |
| trojan-dormant | QCEC | QCEC | QCEC |
| saboteur | fidelity audit | fidelity audit | fidelity audit |

All 90 matrices (3 demos × 2 backends × 15 locks) rejected every attack and accepted every honest compile. The masked Trojan lands at the compiled circuit's midpoint, which moves with the random lock, so its ideal-simulator TVD varies: 0.03-0.13 on QAOA and 0.02-0.13 on VQE, straddling the 0.10 tolerance (40 extra locks per demo, both backends). The saboteur's ESP ratio on FakeTorino is 0.78 (Grover), 0.61-0.71 (QAOA) and 0.54-0.67 (VQE; 0.68 on the current web snapshot's lock).

A detection matrix (one lock, five compiles, no scoring) takes 0.6-3 s after imports (2 of 90 took 5 s and 11 s); a full `pipeline.run` with scorecard and noisy-sim evidence takes 3-11 s. A QCEC check took 0.02-0.34 s in 473 of 474 calls; one took 4.1 s.

### Why 0.90 and 0.10

`bench/thresholds.py` sweeps both thresholds: 3 demos × FakeBrisbane and FakeTorino × 5 fresh locks; per lock, 15 honest compiles (optimization levels 1-3 × transpiler seeds 0-4), 5 saboteur and 5 masked-Trojan compiles (seeds 0-4), each against the pipeline's level-3, seed-7 baseline. Raw numbers in `bench/thresholds.csv`.

![False rejects and missed attacks as the ESP threshold (0.50-1.00) and the naive TVD tolerance (0-0.20) are swept](bench/thresholds.png)

- **ESP ratio threshold.** Honest compiles score 0.912-1.055 (450 compiles), saboteurs 0.540-0.779 (150). Every threshold from 0.78 to 0.91 gives 0 false rejects and 0 missed saboteurs, so 0.90 works, but it sits near the top of that window: the lowest honest compile (VQE-4, FakeBrisbane, level 2) is only 0.012 above it, and at 0.95 71 of 450 honest compiles would be false rejects.
- **Naive TVD tolerance.** No tolerance separates honest compiles from the masked Trojan. At 0.10 there are 0 false rejects, and 127 of 150 masked Trojans pass. The best tolerance in the sweep, 0.025, still lets 54 of 150 through and falsely rejects 5 of 450 honest compiles, on an ideal simulator; on a noisy device honest compiles already land 0.05-0.29 from the ideal histogram (see limitations).

### Scaling

`bench/scaling.py`: one-layer QAOA MaxCut on a random 3-regular graph (fixed graph per size, fresh lock), compiled honestly for FakeBrisbane (optimization level 3, transpiler seed 7), one run per size; times vary between runs. Raw numbers in `bench/scaling.csv`.

| Qubits | Visible CX after padding (decoy pairs) | Compiled 2q gates | Lock | Compile | QCEC check | ESP audit |
|---|---|---|---|---|---|---|
| 4 | 12 (0) | 18 | 0.13 s | 0.26 s | 0.06 s | 0.005 s |
| 6 | 30 (6) | 57 | 0.13 s | 0.28 s | 0.26 s | 0.014 s |
| 8 | 56 (16) | 125 | 0.15 s | 0.26 s | 1.4 s | 0.025 s |
| 10 | 90 (30) | 234 | 0.24 s | 0.25 s | 10.3 s | 0.035 s |
| 14 | 182 (70) | 578 | 0.24 s | 0.33 s | 30 s timeout, no proof | 0.092 s |
| 20 | 380 (160) | 1,508 | 0.37 s | 0.39 s | 30 s timeout, no proof | 0.21 s |

![Time per pipeline step (log scale) and gate counts for QAOA at 4-20 qubits](bench/scaling.png)

Lock, compile and the ESP audit stay under half a second at 20 qubits. QCEC is where it stops scaling: its time grows about 5-7× per 2 qubits from 6 to 10, and at 14 and 20 qubits the pipeline's 30 s timeout fires, so an honest compile there is a false REJECT (the check fails closed; it never turns into an ACCEPT). Given 110 s, QCEC still found no proof: `probably_equivalent` at 14 qubits (simulation found no difference) and `no_information` at 20. No step hit the benchmark's 120 s limit. Padding gives exactly n(n-1) visible CX here (every pair carries the 2 CX of one `rzz`), and the compiled two-qubit count grows faster because far-apart pairs need SWAPs on heavy-hex.

Other QCEC configurations do not fix this yet. `bench/qcec_configs.py` ran the 14-qubit case once per configuration, sequentially, each in a worker killed 30 s after its timeout (QCEC 3.11.0, the version installed here; results in `bench/qcec_configs.csv`):

| Configuration | Timeout | Time | Verdict |
|---|---|---|---|
| Pipeline settings (ZX off) | 300 s | 301 s | `probably_equivalent` |
| ZX checker on | 120 s | 122 s | `probably_equivalent` |
| ZX checker only | 120 s | 1.4 s | `probably_not_equivalent` (wrong: the compile is honest) |
| Construction checker only | 120 s | 125 s | `no_information` |
| Alternating, `gate_cost` scheme with QCEC's Qiskit O3 profile | 120 s | 150 s | killed at the deadline |
| Alternating, `lookahead` scheme | 120 s | 124 s | `no_information` |
| Alternating, `one_to_one` scheme | 120 s | 150 s | killed at the deadline |

None gave a proof, so `verify.py` is unchanged. We did not try QCEC's hybrid Schrödinger-Feynman checker, which only checks approximate equivalence.

## Real hardware runs

Every row was verified before it ran: QCEC plus the ESP audit against the device's live calibration, with the honest compile of the same fresh lock as the baseline (transpiler seed 7). Run 1 is the original `python demo.py --ibm` run (4,000 shots, 1-TVD against a 4,000-shot ideal sample, no noisy-sim prediction). Runs 2 and 3 are `python bench/ibm_runs.py B` and `A` on 2026-10-24 (2,000 shots per circuit, 1-TVD against the exact ideal distribution, prediction from `AerSimulator.from_backend` on the same device). Measured ratio = measured 1-TVD / the honest compile's measured 1-TVD for the same lock and device, the hardware counterpart of the ESP ratio. Naive test = TVD < 0.10 between the measured histogram and the ideal output. Run 4 is the first job from the panel (`python server.py --allow-ibm`, [below](#run-on-ibm-hardware-from-the-panel)) on 2026-10-26: Grover, saboteur vs the honest compile of the same lock, same 2,000 shots, exact ideal and noisy-sim prediction; the honest compile there is the audit's baseline, not a separately judged circuit, so it has no verdict or ESP ratio of its own. Jobs: `dbe5hp7pc3tc739l5al0` (run 1), `dbefmkom94ac738rnks0` (run 2), `dbefmkvsstms73fbvl4g` (run 3), `dbfm3uvgdj9s73bbu600` (run 4); 13 s of QPU time for runs 2-3, 3 s for run 4. Intervals are 95% bootstraps (`bench/confidence.py`: 1,000 resamples of each circuit's measured counts, the ideal reference held fixed); a difference from the honest compile is significant when the ratio interval excludes 1. Raw counts are in `bench/ibm_*.json` and `bench/live_ibm/*.json`, this table in `bench/hardware.csv` (`python bench/compare.py`).

| Run | Device | Circuit | Compiler | Verdict | ESP ratio | Predicted 1-TVD | Measured 1-TVD [95% CI] | Measured ratio [95% CI] | Naive test on hardware |
|---|---|---|---|---|---|---|---|---|---|
| 1 | ibm_fez | Grover | honest | ACCEPT | 1.000 | – | 0.828 [0.815, 0.841] | 1.000 | fail |
| 1 | ibm_fez | Grover | saboteur | REJECT | 0.831 | – | 0.744 [0.729, 0.758] | 0.899 [0.877, 0.921] | fail |
| 2 | ibm_kingston | Grover | honest | ACCEPT | 1.000 | 0.896 | 0.851 [0.833, 0.869] | 1.000 | fail |
| 2 | ibm_kingston | Grover | saboteur | REJECT | 0.894 | 0.820 | 0.724 [0.704, 0.744] | 0.851 [0.822, 0.880] | fail |
| 3 | ibm_fez | Grover | honest | ACCEPT | 1.000 | 0.865 | 0.834 [0.816, 0.852] | 1.000 | fail |
| 3 | ibm_fez | Grover | trojan-overt | REJECT | 1.000 | 0.092 | 0.095 [0.087, 0.103] | 0.114 [0.104, 0.124] | fail |
| 3 | ibm_fez | Grover | trojan-masked | REJECT | 1.000 | 0.852 | 0.812 [0.793, 0.829] | 0.973 [0.944, 1.004] | fail |
| 3 | ibm_fez | Grover | trojan-dormant | REJECT | 0.998 | 0.864 | 0.827 [0.808, 0.845] | 0.991 [0.963, 1.020] | fail |
| 3 | ibm_fez | Grover | saboteur | REJECT | 0.005 | 0.192 | 0.182 [0.168, 0.197] | 0.218 [0.201, 0.237] | fail |
| 3 | ibm_fez | QAOA | honest | ACCEPT | 1.000 | 0.952 | 0.925 [0.900, 0.937] | 1.000 | pass |
| 3 | ibm_fez | QAOA | trojan-overt | REJECT | 1.000 | 0.369 | 0.432 [0.413, 0.451] | 0.467 [0.449, 0.493] | fail |
| 3 | ibm_fez | QAOA | trojan-masked | REJECT | 1.000 | 0.851 | 0.833 [0.810, 0.852] | 0.900 [0.875, 0.932] | fail |
| 3 | ibm_fez | QAOA | trojan-dormant | REJECT | 0.997 | 0.952 | 0.902 [0.877, 0.914] | 0.975 [0.947, 1.002] | pass |
| 3 | ibm_fez | QAOA | saboteur | REJECT | 0.193 | 0.717 | 0.697 [0.673, 0.710] | 0.753 [0.728, 0.778] | fail |
| 3 | ibm_fez | VQE | honest | ACCEPT | 1.000 | 0.972 | 0.873 [0.849, 0.888] | 1.000 | fail |
| 3 | ibm_fez | VQE | trojan-overt | REJECT | 1.000 | 0.634 | 0.639 [0.617, 0.659] | 0.732 [0.708, 0.763] | fail |
| 3 | ibm_fez | VQE | trojan-masked | REJECT | 1.000 | 0.935 | 0.844 [0.823, 0.860] | 0.967 [0.938, 1.001] | fail |
| 3 | ibm_fez | VQE | trojan-dormant | REJECT | 0.997 | 0.974 | 0.883 [0.860, 0.899] | 1.012 [0.981, 1.046] | fail |
| 3 | ibm_fez | VQE | saboteur | REJECT | 0.108 | 0.673 | 0.664 [0.642, 0.684] | 0.761 [0.735, 0.794] | fail |
| 4 | ibm_fez | Grover | honest | – | – | 0.863 | 0.844 [0.827, 0.863] | 1.000 | fail |
| 4 | ibm_fez | Grover | saboteur | REJECT | 0.883 | 0.774 | 0.735 [0.715, 0.755] | 0.870 [0.840, 0.901] | fail |

The verdicts held on every repeat: every honest compile that was judged (runs 1-3) was accepted and all six saboteurs were rejected, including the Grover saboteur on ibm_fez in runs 1, 3 and 4 (ESP ratio 0.831, 0.005 and 0.883 on three calibrations). Every honest-vs-saboteur difference is significant (all six saboteur ratio intervals exclude 1, the closest being run 1's [0.877, 0.921]); of the Trojans whose histograms stay close to honest, only the masked one on QAOA differs significantly from its honest compile, and the dormant and other masked Trojans' intervals include 1.

![Left: ESP ratio before running vs measured fidelity ratio. Right: noisy-simulator 1-TVD vs measured 1-TVD. One point per circuit, colored by compiler](bench/compare.png)

The audit pointed the right way but not to scale: every saboteur it rejected measured worse on the device than its honest compile (measured ratio 0.22-0.90), yet ESP overstates large losses, partly because even a ruined circuit's histogram keeps some overlap with the ideal (ibm_fez saboteurs in run 3: ESP ratio 0.005-0.19, measured 0.22-0.76), while the noisy simulator on the same calibration came within -0.100 to +0.063 of the measured 1-TVD on all 19 circuits (median gap 0.037, below the prediction on 16). On hardware the histogram test could not tell attacks from noise: the dormant Trojan passed it on QAOA (1-TVD 0.902) and failed it on Grover and VQE, the masked Trojan failed it on all three circuits, but the honest compile also failed it in 5 of 6 runs (it passed only on QAOA), while QCEC returned `not_equivalent` for all nine Trojans before anything ran. The mild saboteur the audit accepted on ibm_kingston's live calibration (QAOA and VQE, see [Honest limitations](#honest-limitations)) never ran on hardware, so we have no measured result for it. Limits: these are four jobs on two days (2026-10-24 and 26), only the Grover saboteur on ibm_fez was repeated, and QAOA, VQE and the Trojans ran once each; 2,000 shots per circuit; and calibration drifts between runs: the same Grover saboteur on ibm_fez scored ESP ratio 0.83 in run 1 and 0.005 in run 3, eleven and a half hours later.

### Calibration drift

The audit runs before the job, and the device's calibration moves in between. Right before submission, `verify.recheck` re-runs the audit on the newest calibration: `demo.py --ibm` and `bench/ibm_runs.py` refuse to submit if a circuit that passed at check time now fails, and a test degrades the error rates on the returned circuit's qubits in a copy of FakeBrisbane between check and use and asserts a REJECT. `bench/drift.py` re-audited the exact Grover circuits submitted in runs 1-3 (read back from IBM's job inputs, since the bench files keep no lock key; no new jobs) on the calibration of 2026-10-25 (`bench/drift.csv`; run 1 saved no calibration timestamp, it was submitted at 07:06 UTC on 2026-10-24):

| Run | Device | Calibration then → now (UTC) | Compiler | ESP then → now | ESP ratio then → now | Audit then → now |
|---|---|---|---|---|---|---|
| 1 | ibm_fez | not saved → 2026-10-25 13:45 | honest | 0.868 → 0.858 | 1.000 → 1.000 | `ok` → `ok` |
| 1 | ibm_fez | not saved → 2026-10-25 13:45 | saboteur | 0.721 → 0.765 | 0.831 → 0.892 | `low_fidelity` → `low_fidelity` |
| 2 | ibm_kingston | 2026-10-24 17:49 → 2026-10-25 13:50 | honest | 0.903 → 0.895 | 1.000 → 1.000 | `ok` → `ok` |
| 2 | ibm_kingston | 2026-10-24 17:49 → 2026-10-25 13:50 | saboteur | 0.807 → 0.782 | 0.894 → 0.874 | `low_fidelity` → `low_fidelity` |
| 3 | ibm_fez | 2026-10-24 17:58 → 2026-10-25 13:45 | honest | 0.869 → 0.858 | 1.000 → 1.000 | `ok` → `ok` |
| 3 | ibm_fez | 2026-10-24 17:58 → 2026-10-25 13:45 | saboteur | 0.005 → 0.004 | 0.005 → 0.005 | `low_fidelity` → `low_fidelity` |

Drift moved the same circuit both ways: run 1's saboteur rose from 0.831 to 0.892, 0.008 short of passing, and run 2's fell from 0.894 to 0.874. The swing between runs is larger because the saboteur chooses its qubits from the calibration of the day: on ibm_fez the Grover saboteur scored 0.83 in run 1 and 0.005 in run 3, eleven and a half hours later. Limit: the re-check is relative to the check-time baseline, so drift that degrades the baseline's qubits as much as the returned circuit's (always the case for the honest compile, which is its own baseline) leaves the ratio unchanged, and it never asks whether a fresh compile would now pick better qubits.

## Signed receipts

`receipt.py` turns a verification into an Ed25519-signed JSON receipt: SHA-256 hashes of the original, locked and returned circuits (QASM 3), the verdict, the QCEC verdict, ESP, ESP ratio and threshold, the backend and its calibration time, the TrustPass commit, a UTC timestamp, and a commitment to the lock key, SHA-256(32-byte random salt ‖ canonical JSON of the key). The salt and key stay in `~/.trustpass/keys`, as does the signing key (`~/.trustpass/signing_key`); only the public key is shared.

What it proves: who signed which circuits with what result, and that changing any field breaks the signature; revealing the key and salt later shows which key the verification used, without having published it. What it does not prove: it does not make the compiler honest by itself (the checks do that), and the signer is the verifier, so a receipt is only as trustworthy as whoever ran the checks.

## Scorecard per demo

FakeBrisbane, transpiler seed 7, no extra decoys. Each column is 16 runs (8 honest, 8 saboteur), each with a fresh lock: 8 from our first measurement and 8 re-run on 2026-10-07 with the current code. Numbers are min-max over all 16 plus the web demo's snapshot (`web/snapshot.json`, one more lock per demo), except the two rows marked * (see the first note). Confidentiality numbers come from 30 random wrong keys; "random inputs" means 5 Haar-random input states.

| | Grover-3 | QAOA-4 | VQE-4 |
|---|---|---|---|
| Secret | marked item `101` | 5-edge graph + trained angles | 24 trained weights |
| Key angles | 153 | 84 | 84 |
| Visible CX in locked circuit (decoy share) | 24 (0%) | 12 (17%) | 12 (50%) |
| CX count spread across qubit pairs | 0 | 0 | 0 |
| Wrong-key TVD, \|0⟩ input | 0.78-0.86 | 0.45-0.50 | 0.49-0.54 |
| Wrong-key TVD, random inputs * | 0.43-0.46 | 0.48-0.51 | 0.48-0.50 |
| Know-nothing reference TVD (random output state) * | 0.452 | 0.498 | 0.478 |
| Indistinguishability (1.0 = wrong key no better than knowing nothing) | 0.96-1.00 | 0.97-1.00 | 0.97-1.00 |
| Compiler's view across secrets (lock randomness held fixed) | 8 marked items → 1 identical view | 3 angle settings → 1 identical view; the graph is hidden statistically | 8 weight sets → 1 identical view |
| ESP, honest vs saboteur (ratio) | 0.71 vs 0.38-0.39 (0.54-0.55) | 0.81-0.83 vs 0.55-0.61 (0.67-0.75) | 0.80-0.83 vs 0.55-0.61 (0.66-0.74) |
| Saboteur's qubits: readout error vs device median | 0.060 vs 0.020 | 0.051 vs 0.020 | 0.051 vs 0.020 |
| Noisy-sim fidelity (1 - TVD), honest vs saboteur | 0.71-0.72 vs 0.34-0.36 | 0.90-0.91 vs 0.79-0.83 | 0.89-0.95 vs 0.77-0.84 |
| Trust pillars C / I / Q, honest | 96-100 / 100 / 100, ACCEPT | 97-100 / 100 / 100, ACCEPT | 97-100 / 100 / 100, ACCEPT |
| Trust pillars C / I / Q, saboteur | 96-100 / 100 / 54-55, REJECT | 98-100 / 100 / 67-75, REJECT | 98-100 / 100 / 66-74, REJECT |

Notes:
- \* The know-nothing reference is fixed per demo by the scoring seed's random input states. The current code gives 0.452 / 0.498 / 0.478; our first table said 0.505 / 0.477 / 0.490, which we could not reproduce, so these two rows are from the 8 re-runs only. On one lock, scoring seeds 0-2 move the reference to 0.43-0.46 (Grover), 0.46-0.54 (QAOA) and 0.48-0.52 (VQE), and the wrong-key random-input TVD moves with it; their ratio, indistinguishability, is the number to read.
- Wrong-key numbers only show that the key controls the function. Every qubit ends in a fully keyed block, so a random key looks random for any lock: those numbers cannot reveal a leak, and we no longer report "secret recovered by random keys" as evidence. The check that can fail is the view test: lock the same circuit with every secret and compare what the compiler sees. It correctly fails for QAOA graphs, whose structure is the secret.
- Indistinguishability is noisy too: on one fixed lock, scoring seeds 0-9 give 0.89-1.00 (Grover), 0.95-1.00 (QAOA) and 0.94-1.00 (VQE). With 100 wrong keys and 40 random inputs it is 1.00, 1.00 and 0.99-1.00 (two locks each, the second re-run on 2026-10-07).
- The noisy-sim fidelity is evidence, not the verdict; the verdict uses ESP from calibration data. With the trained QAOA angles (γ = 2.85, β = 0.30, a peaked output) both agree on all three demos.
- The honest ESP ratio is exactly 1.0 by construction: our stand-in honest compiler is the same `transpile` call as the local baseline.

## We red-teamed ourselves

Before submitting, we attacked our own prototype as the untrusted compiler would, knowing the code but not the key. Two rounds of independent attackers, every finding re-verified by a separate agent before we acted on it, then a final review of the verifier: 15 findings, each fixed (with a regression test where the table names one), measured, or documented below. Severity is our own judgement.

**Round 1**

| # | Severity | What it was | How we found it | Fix | Regression test (`test_trustpass.py`) |
|---|----------|-------------|-----------------|-----|----------------------------------------|
| 1 | Critical | The locked circuit kept the original name (`grover-3`) and metadata, which held the secret in plaintext; both survive `transpile`. | Read `.metadata` of the compiled locked circuit: secret recovered on 3 of 3 demos. | Locked circuit is named `locked` with empty metadata. | `test_locked_circuit_reveals_only_a_uniform_skeleton`; the scorecard also caps confidentiality at 0 |
| 2 | Medium | The locked circuit's global phase depended on the secret and leaked 1 bit of the Grover marked item (a parity of its bits). | Locked every candidate marked string offline and matched the visible phase: half the candidates eliminated. | Global phase set to 0; equivalence is checked up to global phase anyway. | `test_locked_circuit_reveals_only_a_uniform_skeleton` |
| 3 | Critical | The pipeline locked with `seed=7`, which is in this public repo, so decoy placement could be replayed. | Replayed the RNG, subtracted the predicted decoys: exact QAOA graph recovered in 100% of random graphs. | The lock always uses OS entropy; `seed` only fixes the transpiler. | `test_pipeline_never_seeds_the_lock` |
| 4 | High | Each QAOA edge and each decoy was a CX-block-CX sandwich, and decoys sat on random pairs, so sandwich counts per qubit pair exposed the graph. | Parsed sandwiches and picked the most likely edge set: exact graph recovered 0.35-0.65 of the time, versus 0.016 by chance. | Decoys pad every qubit pair to the same CX count, are spliced in and locked like real gates, and every CX gets a random direction. | `test_locked_circuit_reveals_only_a_uniform_skeleton` (pair count spread 0); the scorecard also caps confidentiality at 50 |
| 5 | High | QCEC treats unmeasured qubits as don't-care, so a compiled circuit with an output measurement deleted still passed as equivalent. | Deleted one measurement from an honest compile: QCEC said `equivalent_up_to_global_phase`. | Compare the classical-bit → logical-qubit output map (through the final layout) before QCEC. | `test_verifier_fails_closed` (dropped and re-routed measurement) |
| 6 | Medium | A single `delay` or `reset` from the compiler crashed QCEC, so the pipeline raised instead of returning a verdict (denial of service). | Inserted one delay, then one reset, before measurement. | Fail closed: any exception in the check is REJECT `unverifiable:<exception>`. Since then, delays (logically the identity) are removed before QCEC and charged as idle time by the fidelity audit, so the inserted delay is still a REJECT, now `low_fidelity`; a reset is still `unverifiable`. | `test_verifier_fails_closed` (delay, reset); `test_scheduled_compile_accepted` |
| 7 | Medium | QCEC's checkers raced, so the same honest compile sometimes came back `no_information` (a false REJECT). | Ran the check repeatedly on one honest compile. | ZX checker off (`run_zx_checker=False`); the verdict is now stable. | `test_verifier_fails_closed` (5 honest passes in a row) |

**Round 2**, attacking the fixed code:

| # | Severity | What it was | Fix | Regression test / note |
|---|----------|-------------|-----|------------------------|
| 8 | High | QCEC occasionally never returned (4 of ~28 runs under heavy load); the fail-closed fix only caught exceptions. | QCEC runs sequentially (`parallel=False`) with a 30 s timeout, so slow means REJECT, never a hang; the web server runs one pipeline at a time. | `test_verifier_fails_closed` (honest passes repeatedly) |
| 9 | High | Decoys landed at uniform slots of the gate stream while real interactions kept the author's order, so an exact Bayes attacker recovered the QAOA graph about 0.40-0.45 of the time (chance 0.016). | Commuting `rzz` runs are shuffled and each decoy pair lands at a uniform boundary between two-qubit instructions, never inside a real interaction. The visible order is then a uniform permutation of pairs: an independent check over 800 locks found pair positions uniform (p = 0.62-0.93) and no difference between graphs (p = 0.69). | no test; measured (800 locks) |
| 10 | High | A qubit pair whose CX gap to the busiest pair is odd cannot be padded with CX pairs; on a Bernstein-Vazirani circuit the secret was readable 100% of the time. | `lock()` refuses such circuits instead of leaking silently. A 3-CX identity gadget is Round 2. | `test_lock_refuses_odd_gaps` |
| 11 | Medium | The random-key confidentiality metric stays near chance for any lock, so it cannot detect a leak. | Replaced as evidence by the view test (identical view for every secret); the random-key number is kept only as a key sanity check. | `test_view_never_depends_on_the_secret` |
| 12 | Medium | Decoys are adjacent CX-block-CX pairs; where real interactions are lone CX (ansatz layouts, oracles), an attacker can peel the decoys off. | Documented. No demo secret lives in that skeleton (VQE's layout is the public ansatz; Grover's skeleton is identical for every marked item). | no test; limitation below |
| 13 | Low | Padding to the busiest pair's count reveals that count (for QAOA, the layer count p). | Documented. | no test; limitation below |
| 14 | Low | Canonicalising gate order and key names was proposed after round 1. | Not needed once decoys land at uniform boundaries; measured no gain. | n/a |

The verifier red team in round 2 did not finish; round 1's verifier attacks (dropped and re-routed measurements, delay and reset, clbit scrambles, a coherence saboteur) and the final review below are the coverage we have.

**Final review** of the verifier, before submission:

| # | Severity | What it was | How we found it | Fix | Regression test (`test_trustpass.py`) |
|---|----------|-------------|-----------------|-----|----------------------------------------|
| 15 | High | ESP scores any gate missing from the calibration data as error-free, so a saboteur could pad with self-cancelling pairs on uncoupled qubits (or with gates the device does not have) at no cost in the audit. Also, the equivalence check accepted QCEC's `equivalent_up_to_phase`, which is a relative phase, i.e. a different unitary. | Added a CX pair on uncoupled qubits (0, 2) to an honest compile: QCEC said equivalent, ESP ratio 1.0, verdict ACCEPT, on FakeBrisbane and FakeTorino. | The audit fails closed: any gate the device cannot run on those qubits is REJECT `not_native`, whatever the ratio. Only `equivalent` and `equivalent_up_to_global_phase` pass QCEC. Re-checked on 360 honest compiles: 0 false rejects. | `test_verifier_fails_closed` (CX and ECR pairs on an uncoupled pair; rz(0.35) before a measurement) |

The relative-phase part is defence in depth: QCEC never returned `equivalent_up_to_phase` in our runs, and every relative-phase Trojan we tried (rz(0.35), Z, S, rz(π), rz(0.001) before a measurement) was already rejected as `not_equivalent`, so that test guards against regressions and does not show a hole existed. The padding hole was real and is closed.

What remains after the fixes is listed under limitations: lone-CX skeletons, the idle-time model for scheduled compiles, and the oracle-guided attacker we declare out of scope.

## Honest limitations

- **Locking costs gates.** Compiled for FakeBrisbane, transpiler seed 7, 8-11 fresh locks each plus 8 more re-run on 2026-10-07 and the web snapshot's lock:

  | | 2q gates, plain → locked | Depth, plain → locked |
  |---|---|---|
  | Grover-3 | 39 → 45 | 174 → 367-390 |
  | QAOA-4 | 16 → 18-21 | 85 → 140-168 |
  | VQE-4 | 6 → 18-24 | 30 → 133-185 |

  The fidelity audit compares against a locked baseline, so it does not see this cost; it is the price of confidentiality.
- **Padding grows as O(n²).** Every one of the n(n-1)/2 qubit pairs gets as many CX as the busiest pair: 3 pairs at 3 qubits, 6 at 4, 190 at 20, 8,001 at 127. Our demos are dense or tiny, so it is cheap here (0-3 decoy pairs). A sparse 20-qubit circuit whose busiest pair carries 2 CX gets at least 380 CX after locking, and on heavy-hex hardware the far-apart pairs then need SWAPs. If a pair's gap to the busiest pair is odd, `lock()` refuses the circuit rather than leave a visible gap (none of our demos hits this).
- **The CX skeleton is flattened, not hidden.** The compiler still sees the qubit count, the total CX count (which reveals the busiest pair's count, e.g. QAOA's layer count) and the CX blocks. For QAOA the order of the blocks is a uniform shuffle (finding 9), so the graph is hidden statistically, not exactly. Decoys hide the graph only when every real interaction is itself a CX-block-CX pair (QAOA's `rzz`); for lone-CX circuits an attacker can peel the decoys off and read the real skeleton (finding 12).
- **Scheduled compiles are judged by a simple idle model.** An honest ALAP-scheduled compile is now verified instead of rejected: with the pipeline's settings (optimization level 3, transpiler seed 7) Qiskit's `scheduling_method="alap"` adds 132-169 delays to our demos, passes QCEC and scores an ESP ratio of 1.00 on all 3 demos × FakeBrisbane and FakeTorino. Counting idle time also makes weaker honest compiles look worse: of 90 ALAP compiles at optimization levels 1-3 × transpiler seeds 0-4 (one lock per demo per backend) all 90 passed QCEC and 23 were rejected by the audit (ratios below 0.90, down to 0.72; 22 of them at levels 1-2), where unscheduled they would pass. The idle term is an estimate from T1/T2 alone, with no crosstalk or dynamical decoupling modelled, and we have not tested dynamical-decoupling compiles. Reset, feed-forward and anything else QCEC cannot reason about are still a REJECT.
- **The threat model assumes compiler ≠ executor, and that the compiler never sees results.** If one party both compiles and runs the circuit, it sees the unlocked circuit: TrustPass still checks integrity and fidelity, but no longer gives confidentiality. An attacker who sees input/output of the unlocked circuit is out of scope, and our own measurements show why: Grover's output *is* its secret (one shot of Grover-3 reveals the marked item with probability 0.945), and for a 2-qubit, 1-edge QAOA (18 key angles), fitting every key angle by least squares to the exact output distributions of 6 random product-state inputs reproduced held-out inputs exactly and read back (γ, β) = (0.79, 0.39) for the true (0.80, 0.40) on a 0.049 grid. With 1-4 inputs the fit did not generalise (held-out TVD 0.27-0.46).
- **The key is a list of continuous angles, not bits.** There is no key-length security argument; leakage is measured empirically against random guessing, not proven.
- **The naive test is an ideal-simulator best case.** TVD < 0.10 stands in for "the histogram looks right", and we run it noiselessly, the most favourable case for it. An honest compile on the FakeBrisbane noise model already lands 0.05-0.29 TVD from the ideal histogram (1 - noisy-sim fidelity above), so a user reading real hardware output could not demand tighter, and the occasional naive catch of the masked Trojan on QAOA and VQE would vanish in that noise.
- **The fidelity audit trusts calibration data.** ESP ignores crosstalk, coherent errors and (unless the compile is scheduled) idle time, the 0.90 threshold is a heuristic, and the audit needs a local compile as a baseline. It checks that the returned circuit is not measurably worse than that baseline; it does not prove the compile is good. A better third-party compiler simply scores above 1.0. It can miss a mild saboteur: `bench/live_targets.py` ran the detection matrix against the live calibration of ibm_fez, ibm_kingston and ibm_marrakesh (2026-10-24, no jobs, one fresh lock per circuit), and on ibm_kingston the saboteur's qubits were barely worse than the honest layout's (ESP ratio 0.921 on QAOA, 0.912 on VQE), so it was accepted; the other 43 of 45 verdicts were as expected.
- **Small, simulated, self-built.** Demos use 3-4 active qubits on fake backends; our real-hardware results are the four runs on ibm_fez and ibm_kingston above, from two days. In the scaling benchmark (QAOA on random 3-regular graphs) QCEC proves equivalence up to 10 qubits and times out at 14 and 20, so beyond about 10 qubits an honest compile is a false REJECT. The attacks are our own stand-ins modelled on the literature, not captured from real malicious compilers.

## Round 2 roadmap

- **Oracle-guided attack suite**: run the Zhang & Liu style attack (and angle-fitting attacks) against larger locked circuits and report key recovery.
- **General decoy placement**: extend the uniform-boundary placement beyond commuting `rzz` runs with commutation analysis, add a 3-CX identity gadget for odd gaps, and make decoys that survive peeling on lone-CX circuits.
- **Cheaper padding**: pad only pairs a plausible compiler output could use, and measure what that gives back to the attacker.
- **Dynamical decoupling**: test DD-padded compiles against the idle model, and compare that model with measured fidelity.
- **Qiskit transpiler-plugin packaging**: wrap lock, unlock and verify around any third-party transpiler plugin or Qiskit Function call.
- **Repeated hardware runs**: the same circuits on several days and devices, so calibration drift and shot noise can be separated from the audit's own error.
- **QCEC past 10 qubits**: our scaling benchmark times out at 14 qubits; try other QCEC configurations (the ZX checker is off for stability, finding 7) and longer timeouts.
- **QSSP-aligned scoring**: map the scorecard onto the Quantum Software Security Posture (QSSP) score proposed by Rahman et al. (gap 4).

## Quickstart

Tested with Python 3.12.10 on Windows 11.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; on Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

python server.py                                             # the instrument UI, live runs: http://localhost:8600
python server.py --export                                    # regenerate web/snapshot.json (30 runs + 6 matrices, ~4 min) and web/plant.json (~30 s)
python demo.py                                               # the whole story in the terminal (Grover on FakeBrisbane), ~25 s
python demo.py --matrix                                      # only the detection matrix, ~10 s
python demo.py --circuit QAOA --backend FakeTorino --matrix  # another demo on the CZ-basis backend
python demo.py --decoys 1 --seed 3                           # 1 extra decoy round, transpiler seed 3
python test_trustpass.py                                     # 15 checks, ~20 s (pytest works too)
```

`--decoys` adds extra padding rounds on top of the uniform pair counts (default 0). `--seed` only fixes the transpiler (default 7); the lock always draws fresh OS randomness, so key angles, CX counts and depth can differ slightly between runs.

`python demo.py --ibm` runs an honest vs sabotaged compile on real IBM hardware with an IBM Quantum account you have saved yourself; our results are under [Real hardware runs](#real-hardware-runs). `python bench/ibm_runs.py` runs the larger hardware benchmark (it asks before every submit and stops under 4 minutes of QPU time).

### Run on IBM hardware from the panel

`python server.py --allow-ibm` (with an IBM Quantum account saved on that machine) adds a **Run on real IBM hardware** unit below the panel; without the flag the endpoints answer 403 and the unit stays hidden, as it does on GitHub Pages. Pick ibm_fez or ibm_kingston; the unit shows the device's queue, the account's remaining QPU time and the calibration time, and asks once before submitting. It sends the panel's circuit and SOURCE choice (or the Trojan you planted): one fresh lock, the chosen compile and an honest compile of the same lock as the baseline, QCEC plus the fidelity audit on the device's live target, `verify.recheck` right before submitting, then one SamplerV2 job of exactly 2 circuits × 2,000 shots. The verdict is shown before the job runs; when it finishes, the unit shows measured 1-TVD for both circuits, their ratio and the naive test on the real histogram. Guards: one job in flight at a time, no submit under 2 minutes of QPU time, at most 6 submits per server run, ibm_marrakesh refused (offline until 2026-12-09); the server listens on 127.0.0.1 only. Every job is saved to `bench/live_ibm/<job_id>.json`. Queue time is unpredictable: our first panel job (Grover + saboteur on ibm_fez, `dbfm3uvgdj9s73bbu600`, 2026-10-26) waited about a second and used 3 s of QPU time, while our 2026-10-24 ibm_marrakesh job was still queued when the hardware table above was written.

As one command (`pip install -e .` installs `trustpass`; keys and the signing key live in `~/.trustpass`, never in the repo):

```bash
trustpass lock in.qasm -o locked.qasm                                # OS-entropy lock, key saved locally
trustpass verify in.qasm returned.qasm --backend FakeBrisbane        # QCEC + fidelity audit; exit 0 ACCEPT, 1 REJECT
trustpass receipt verify receipt.json --pubkey ~/.trustpass/signing_key.pub   # VALID / INVALID
trustpass keygen -o key.pub                                          # export your public key to share
```

`returned.qasm` is whatever the third-party compiler sent back for `locked.qasm` (QASM 2 or 3). `--backend` also takes `ibm_fez`, `ibm_kingston` and `ibm_marrakesh`, which read the live calibration with your saved IBM account and never submit a job.

From Python:

```python
from qiskit_ibm_runtime.fake_provider import FakeBrisbane
from circuits import grover
from pipeline import run

report = run(grover("101"), FakeBrisbane(), mode="saboteur", seed=7)
print(report["trust"])  # e.g. {'confidentiality': 100, 'integrity': 100, 'quality': 55, 'verdict': 'REJECT'}
```

| File | Role |
|------|------|
| `circuits.py` | Victim circuits (Grover, QAOA, VQE), each carrying a secret |
| `lock.py` | `lock`, `unlock`, `random_key` |
| `compilers.py` | Honest and malicious stand-in compilers |
| `verify.py` | Naive test, output-map + QCEC equivalence, ESP fidelity audit, run-time re-check, noisy-sim evidence |
| `score.py` | Confidentiality, overhead and trust scorecard |
| `receipt.py` | Ed25519-signed receipts with a commitment to the lock key |
| `cli.py`, `pyproject.toml` | The `trustpass` command: lock, verify, receipt verify, keygen |
| `pipeline.py` | `run` and `detection_matrix` |
| `index.html`, `web/` | The instrument UI (hand-built HTML/CSS/JS, self-hosted fonts, `snapshot.json`) |
| `server.py` | Serves the UI and a small JSON API over the real pipeline (including `/api/plant`, and `/api/ibm/*` with `--allow-ibm`); `--export` writes the snapshot and `web/plant.json` |
| `assets/plates/` | Panel hardware images (knobs, lever, lamps, screws), each with its generation prompt embedded |
| `.impeccable/`, `DESIGN.md`, `PRODUCT.md` | The UI design record: product brief and decisions (`PRODUCT.md`), design tokens and rules (`DESIGN.md`), and the Impeccable workflow's comps, reviews and captures (`.impeccable/`) |
| `demo.py` | The terminal demo |
| `test_trustpass.py` | 14 checks, including regressions for the red-team findings and the calibration-drift re-check |
| `bench/` | Measurements behind the README: threshold sweep, scaling, live-calibration matrix, real hardware runs and their comparison, README capture (`pip install -r bench/requirements.txt`) |

## How we built this (AI use)

- The team chose the problem and the scope, made the design decisions, and ran and checked the experiments.
- Anthropic's Claude (Claude Code) was our coding and research assistant: it drafted code, ran the red-team attacks and many of the measurement runs, and helped build the UI (the Impeccable design workflow, and Figma image generation for the panel hardware renders in `assets/plates/`).
- Every number in this README comes from code in this repo that anyone can re-run.

## Team

Team name: Team Kairo

College: RV College of Engineering

| Name | Role |
|---|---|
| Dev Keerthi P | Ideation & Backend |
| Abijith Kumar Sinha | Full Stack |
| Saniya Ali Kokkanti | Frontend & Presentation |
