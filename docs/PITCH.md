# TrustPass: Round 1 pitch (slide text)

Slide-by-slide text for the organisers' Canva template: 10 slides, the limit. The bold line and bullets are what goes on the slide (60-80 words each); speaker notes are for the presenter only.

**Where the numbers come from.** The README (measured 2026-10-06 and 2026-10-07 with `demo.py` and the repo code, on simulated IBM devices: FakeBrisbane, 127-qubit Eagle, ECR gates; FakeTorino, 133-qubit Heron, CZ gates; transpiler seed 7) and the web UI's snapshot (`web/snapshot.json`), which gives the Grover-on-FakeBrisbane figures on slide 6. The false-reject sweep on slide 8 and finding 15 on slide 9 were measured on 2026-10-07 after the last verifier fix. The lock draws fresh OS randomness on every run, so numbers move a little from run to run. Quote the ranges as they are; do not round them in our favour.

**Check before presenting.** Three facts in the speaker notes and on slide 2 are general knowledge, not from our runs: the National Quantum Mission figures on slide 10 (as DST and PIB state them: approved by the Union Cabinet in April 2023, ₹6,003.65 crore from 2023-24 to 2030-31, aiming at intermediate-scale quantum computers with 50-1,000 physical qubits in 8 years), QpiAI-Indus being a 25-qubit machine reached through QpiAI's cloud stack (slide 2), and IBM's Qiskit Transpiler Service returning a compiled circuit (slide 2). Check each against an official source, or drop it.

---

## Slide 1: Title and team

**TrustPass: zero-trust compilation for quantum circuits**

- Send your circuit to a compiler you do not trust. It never sees your gate angles, and nothing it returns runs until it passes our checks.
- Caught **4 of 4** attacks in all 90 test matrices; the usual histogram check caught 1 or 2.
- Q-HACK INDIA 2026 · Quantum Security & Cryptography track
- Team [name]: [Name], [Name], [Name] · [College]
- github.com/Devkeerthi-code/TrustPass · Live demo: devkeerthi-code.github.io/TrustPass

*Speaker note:* Compiling a quantum circuit often means running someone else's code on it. TrustPass lets you do that without trusting them. [One line per person on what they built.]

---

## Slide 2: The problem

**Your circuit passes through someone else's compiler**

- **Compile-only third parties see the whole circuit:** Qiskit transpiler plugins (any pip package can supply one) and remote services returning a compiled circuit, e.g. IBM's Qiskit Transpiler Service.
- **They could** steal it, plant an answer-changing Trojan, or park it on the noisiest qubits.
- **Full-stack clouds** compile and run: checks work, secrecy does not.
- No attack is publicly reported yet; research assumes this threat model.
- Today's histogram check catches **1-2 of our 4** attacks.

*Speaker note:* Three ways to abuse a compiler: steal the circuit, change it, or quietly make it worse. A plugin or a compile service only hands a circuit back, so it never sees your results; that is the case TrustPass is built for. When one party both compiles and runs, as with QpiAI's cloud stack for India's 25-qubit QpiAI-Indus, that party sees the unlocked circuit: we still check integrity and fidelity, but cannot keep it secret. We are not claiming these attacks have happened; the papers on the next slide assume this attacker, and we built the defence for it. The usual check, run on |0…0⟩ and eyeball the histogram, catches the obvious Trojan only (on QAOA and VQE it sometimes also catches the masked one).

---

## Slide 3: Research gaps

**Seven papers; none locks, verifies and audits together**

| Work | Gap → TrustPass |
|------|-----------------|
| E-LoQ, HOST 2025 | Locks, never checks the result → we verify it |
| CLOAQ, ISCAS 2026 | \|0⟩ inputs only → proof covers every input |
| Zhang & Liu 2025 | I/O pairs break split compilation → measured; Round 2 |
| Rahman et al. 2026 | Ad hoc metrics → one scorecard |
| John, Golla, Wang 2025 | Dormant Trojans → caught by QCEC |
| Zheng, Shang, Tan 2025 | 91.6%-accurate classifier → formal proof |
| MacNeil, QSec 2025 | Noise-fingerprint tamper check → we check before running |

*Sources (small print in the slide footer):* arXiv:2412.17101 · arXiv:2602.23569 · arXiv:2511.04842 · arXiv:2608.05831 · arXiv:2502.08880 · doi:10.1007/978-981-95-4791-3_6 · doi:10.1145/3733825.3765283

*Speaker note:* To our knowledge, no prior tool combines locking, formal verification and a fidelity audit in one pipeline. Row by row: we verify what comes back; the equivalence proof covers every input, not just |0⟩; the oracle-guided attack is out of our threat model, we measured it on a small QAOA and a defence is Round 2; one fixed scorecard for every run; the dormant Trojan is one of our attacks; a formal proof instead of a classifier that misclassifies some circuits; and we check the returned circuit before it runs, with no extra qubits, in the same pipeline as the lock. What is new against prior obfuscation: split compilation (Saki et al., ICCAD 2021) never shows one compiler the whole circuit, and E-LoQ locks the circuit but is evaluated for concealment only. We show one compiler the whole locked circuit, pad every qubit pair to the same CX count, and test that the compiler's view is identical for every secret (8 Grover marked items, 8 VQE weight sets, 3 QAOA angle settings: one view each). And we audit what comes back against a free local compile, so sabotage that stays equivalent is caught, not only Trojans.

---

## Slide 4: Why quantum computing is required

**Quantum hardware makes this attack easy to hide**

- **Compilation is device-specific:** routing onto one chip's qubit connections and around its noisy qubits, so it gets outsourced.
- **The secrets are quantum:** rotation angles, QAOA graphs, VQE weights.
- **Outputs are probabilistic,** so test runs fail: the masked Trojan moves Grover's histogram **0.016-0.017**; noise alone moves an honest compile 0.05-0.29.
- **Checking needs quantum tools:** operation equivalence, noise-aware fidelity.
- **Sabotage by placement** exists only on noisy quantum hardware.

*Speaker note:* A classical compiler bug is caught by running tests and comparing outputs. A quantum circuit gives a different histogram every run and noise blurs it, so a small Trojan hides inside the noise (both numbers are total variation distance, from our README). That is why we prove equivalence of the quantum operation with MQT QCEC instead of sampling, and why sabotage is possible at all: the same logical circuit can be placed on good or bad physical qubits, and only a noise-aware check (ESP from the device's calibration data) can tell.

---

## Slide 5: Solution and architecture

**Lock → untrusted compile → unlock → verify → score**

*Diagram (labels on the slide):* **Your machine (trusted):** Circuit → Lock · **Third party (untrusted):** Compile · **Your machine again:** Unlock → Verify → Score → *ACCEPT only* → **Hardware provider:** Run

- **Lock:** every single-qubit angle becomes a key symbol (Grover: **153**, 0 real angles); decoy CX pairs equalise every qubit pair.
- **Verify:** outputs land on the right qubits, then MQT QCEC proves equivalence for every input.
- **Audit:** estimated success probability (ESP) ≥ 0.90 of a free local compile.

*Speaker note:* Draw three zones, left to right: your machine in green, holding a key icon that never leaves it; the third-party compiler in red; the hardware provider in grey. Arrows: "locked circuit: angles are symbols" from Lock to Compile, "compiled locked circuit" back to Unlock. The key values never leave your machine, and an honest compiler works unchanged because compilers already handle symbolic parameters. ESP is the product of (1 − error) over every gate and measurement, from the device's calibration data; the audit also rejects any gate the device cannot run. ACCEPT only if both checks pass, and you submit the final circuit to the hardware provider yourself, so the compiler never sees results.

---

## Slide 6: Detection matrix and saboteur evidence

**Histogram check: 1 of 4 attacks on Grover. TrustPass: 4 of 4.**

| Compiler | Naive test | QCEC | Audit | Verdict |
|---|---|---|---|---|
| Honest | pass | pass | pass | **ACCEPT** |
| Trojan, visible | CAUGHT | CAUGHT | pass | **REJECT** |
| Trojan, masked | pass | CAUGHT | pass | **REJECT** |
| Trojan, dormant | pass | CAUGHT | pass | **REJECT** |
| Saboteur | pass | pass | CAUGHT | **REJECT** |

- **Saboteur:** truly equivalent, on qubits with 6.0% readout error (median 2.0%). ESP **0.389** vs honest 0.710; noisy-sim right answer 66% → 31%.
- 90 matrices (3 circuits × 2 devices × 15 locks): all correct.

*Speaker note:* The table is Grover on FakeBrisbane, a 127-qubit IBM device model. The left column is what people do today; it catches only the visible Trojan (on QAOA and VQE it sometimes also catches the masked one, because that Trojan's distance straddles the 0.10 tolerance). The proof catches every Trojan. The saboteur really is equivalent, so QCEC passes it, and only the audit catches it: its ESP ratio is 0.55, below the 0.90 threshold. On the noisy simulator the marked item 101 comes out 66% of the time from an honest compile and 31% from the saboteur's. The noisy simulation is evidence only; the verdict uses ESP. The 90 matrices cover Grover, QAOA and VQE on FakeBrisbane and FakeTorino, each with a fresh random lock.

---

## Slide 7: Implementation / technology stack

**Python on Qiskit, runs on a laptop: a detection matrix usually takes 0.6-3 s**

- **Qiskit 2.5:** circuits, transpiler, symbolic parameters as the key.
- **IBM device models** (qiskit-ibm-runtime 0.50): FakeBrisbane, 127-qubit Eagle; FakeTorino, 133-qubit Heron, both carrying real IBM calibration snapshots.
- **Qiskit Aer 0.17:** noisy simulation, as evidence.
- **MQT QCEC 3.10:** formal equivalence checking.
- **Pipeline modules:** circuits · lock · compilers · verify · score · pipeline.
- **UI:** hand-built HTML/CSS/JS instrument; GitHub Pages serves a snapshot of real runs.
- **9 automated tests**, about 10 s.

*Speaker note:* Everything is open source and runs on Python 3.12. `lock.py` rewrites the circuit; `compilers.py` holds five stand-in compilers (honest, three Trojans, saboteur); `verify.py` runs the naive test, the output-map check plus QCEC, and the ESP audit; `score.py` builds the scorecard; `pipeline.py` ties them together. `server.py` serves the instrument UI with live runs; `server.py --export` writes the snapshot the public page uses. A QCEC check took 0.02-0.34 s in 473 of 474 calls. The tests include regressions for the red-team findings.

---

## Slide 8: Confidentiality, cost and false rejects

**8 secrets in, 1 identical compiler view out**

- **View test (it can fail):** Grover's 8 possible secrets give the compiler 1 identical circuit. VQE: 8 weight sets, 1 view.
- **QAOA graph:** hidden statistically; block order is a uniform shuffle (800 locks, p = 0.62-0.93).
- **Cost:** Grover 39 → 45 two-qubit gates; VQE pays most, 6 → 18-24.
- **False rejects:** **0 of 360** honest compiles (3 circuits × 2 devices × optimisation levels 1-3 × 20 seeds). Lowest ESP ratio 0.948, threshold 0.90.

*Speaker note:* The compiler learns nothing about the angles: it sees no gate angles, no name or metadata, and the same CX count on every qubit pair. The view test holds the lock's randomness fixed and locks the same circuit with every possible secret; it correctly fails for QAOA graphs, whose structure is the secret, so for graphs we measured instead: block positions were uniform and no different between graphs. VQE pays most because its 6 qubit pairs all need padding to the same count. The false-reject sweep compiled every demo honestly at three optimisation levels and 20 transpiler seeds on both device models; every one was accepted, and the lowest ESP ratio sat about 0.05 above the threshold. If a judge asks how we know the compiler learns nothing about the angles: the view test, and two rounds of attackers trying to read the secret off the locked circuit.

---

## Slide 9: We red-teamed ourselves

**We attacked our own tool: 15 findings, each fixed or documented**

| What we broke | Fix |
|---|---|
| Name and metadata carried the secret in plain text | Both stripped |
| A deleted measurement still passed QCEC | Output-to-qubit map checked first |
| Self-cancelling CX on unconnected qubits scored error-free: ACCEPT | Audit rejects gates the device cannot run |

- Attackers played the malicious compiler: our code, not the key.
- Each finding confirmed before fixing; 9 automated tests guard the fixes.

*Speaker note:* Two rounds of attackers found 14 findings; a final review before submitting found the 15th, the last row. Before that fix, a self-cancelling CX pair on an unconnected qubit pair came back with an ESP ratio of 1.0 on both device models, and QCEC said equivalent, so the verdict was ACCEPT. Other examples: the public transpiler seed let an attacker replay decoy placement (100% QAOA graph recovery), and a single delay crashed the checker, which now fails closed. The ones we did not fix are listed as limits in the README. The attacks were run with Claude Code; the README's AI-use section says who did what.

---

## Slide 10: Limits, roadmap and impact

**Next: real IBM hardware, bigger circuits, a drop-in plugin**

| Limit today | Round 2 |
|---|---|
| Simulated devices; ESP trusts calibration data | Real IBM hardware runs |
| 3-4 qubit demos; padding grows as n²; QCEC proves QAOA up to 10 qubits, times out at 14 | Cheaper padding, QCEC past 10 qubits |
| Wraps our own stand-in compilers | Package as a Qiskit transpiler plugin |
| Idle time of scheduled compiles only estimated from T1/T2 | Test dynamical decoupling and the idle model on hardware |

- **Impact:** pharma (VQE weights) and finance (QAOA angles) keep trained parameters from the compiler; compiler vendors get a receipt customers can check.

*Speaker note:* `demo.py --ibm` is written to submit an honest and a sabotaged compile to the least busy real IBM device with your own IBM Quantum account; we have no hardware results yet. Padding gives every qubit pair the busiest pair's CX count: 6 pairs at 4 qubits, 8,001 at 127. The QAOA graph is hidden statistically, not exactly, and an attacker who sees input/output pairs of the unlocked circuit is out of scope; an oracle-guided attack suite is also on the Round 2 list. In India, the National Quantum Mission (₹6,003.65 crore, 2023-24 to 2030-31) aims at intermediate-scale quantum computers with 50-1,000 physical qubits; anyone who compiles circuits for them through a third party faces the same question. The receipt for vendors is an equivalence proof plus an ESP ratio of at least 0.90.

---

## Demo video script

The video script lives in [VIDEO_SCRIPT.md](VIDEO_SCRIPT.md). It runs about 2:45 against a 3-minute limit, uses the team's own voices, and includes the architecture walkthrough and a terminal run that the rules require.
