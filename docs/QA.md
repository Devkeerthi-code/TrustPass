# TrustPass: hard questions and answers (Q&A prep)

Every answer is drawn from the README and the code; the source is in brackets. Numbers are from real pipeline runs.

## Thresholds and the audit

**1. Why is the fidelity threshold 0.90?**
It is a heuristic, and the README says so [README, Honest limitations]. We then swept it: over 450 honest compiles (3 demos × FakeBrisbane and FakeTorino × 5 fresh locks × optimization levels 1-3 × transpiler seeds 0-4) and 150 saboteur compiles, every threshold from 0.78 to 0.91 gave 0 false rejects and 0 missed saboteurs [README, Why 0.90 and 0.10; `bench/thresholds.py`]. 0.90 sits inside that window.

**2. The lowest honest compile scored 0.912. Isn't a 0.012 margin too thin?**
Yes, it is thin, and the README says 0.90 sits near the top of the safe window [README, Why 0.90 and 0.10]. Moving to 0.95 would falsely reject 71 of 450 honest compiles, and moving down toward 0.78 still catches every saboteur we built (they score 0.540-0.779). So there is room to lower it, but a stealthier saboteur than ours could land in that gap.

**3. Your honest compiler is the same `transpile` call as the baseline. Isn't an ESP ratio of 1.0 trivial?**
Yes: the README notes that the honest ratio is exactly 1.0 by construction [README, Scorecard notes]. That is why we also audited honest compiles that differ from the baseline: 0 false rejects in 360 compiles at levels 1-3 and 20 transpiler seeds [README, How TrustPass works, step 4], and 0.912-1.055 across 450 compiles with fresh locks [README, Why 0.90 and 0.10].

**4. Why ESP from calibration data, and not a noisy simulation, for the verdict?**
ESP is the product of (1 - error) over every gate and measurement from the backend's calibration data [`verify.py`, `esp`], so it is deterministic, needs no shots, and stays cheap at scale (0.21 s at 20 qubits) [README, Scaling]. The noisy-sim fidelity is reported as evidence, not the verdict, and with the trained QAOA angles both agree on all three demos [README, Scorecard notes]. ESP's known gaps are crosstalk, coherent errors and (for unscheduled compiles) idle time [README, Honest limitations].

**5. Isn't the naive |0⟩ test a straw man?**
It stands in for what users do today, and we run it in its best case: an ideal simulator with a TVD tolerance of 0.10 [README, Honest limitations; `verify.py`, `naive_check`]. Even so, no tolerance separates honest compiles from the masked Trojan: at 0.10, 127 of 150 masked Trojans pass, and the best tolerance (0.025) still lets 54 through while falsely rejecting 5 of 450 honest compiles [README, Why 0.90 and 0.10].

## Verification

**6. QCEC timed out at 14 qubits. Does the equivalence check scale?**
Not far yet. In our QAOA scaling benchmark QCEC proves equivalence up to 10 qubits (10.3 s), then hits the pipeline's 30 s timeout at 14 and 20 qubits; with 110 s it still found no proof [README, Scaling]. The check fails closed, so that is a false REJECT, never a false ACCEPT [`verify.py`, `check_function`]. We tried seven QCEC configurations on the 14-qubit case (300 s timeout, the ZX checker, construction only, three alternating schemes) and none gave a proof; the best was `probably_equivalent` after 300 s [README, Scaling; `bench/qcec_configs.py`].

**7. A compiler that schedules the circuit adds delays. Do you reject that?**
No longer. Delays are logically the identity, so QCEC checks a copy without them, and the fidelity audit charges their idle time as ESP × ∏ exp(-t / min(T1, T2)) over delays on the qubits in use, after ALAP-scheduling both the compile and the baseline locally [README, How TrustPass works, step 4; `verify.py`]. An honest ALAP compile at the pipeline's settings scores 1.00 on all 3 demos × 2 backends, but 23 of 90 weaker ALAP compiles (mostly levels 1-2) are rejected because idle time now counts, and the idle model is a T1/T2 estimate only [README, Honest limitations].

## Confidentiality

**8. How do you know the locked circuit leaks nothing? A wrong key giving random output proves little.**
Agreed: the README says wrong-key numbers only show that the key controls the function, since every qubit ends in a fully keyed block [README, Scorecard notes]. The check that can fail is the view test: lock the same circuit with every secret and compare what the compiler sees; 8 Grover marked items, 8 VQE weight sets and 3 QAOA angle settings each give one identical view, and the test correctly fails for QAOA graphs [README, Scorecard per demo; `score.py`, `secret_blind`]. There is no key-length security argument; the key is continuous angles [README, Honest limitations].

**9. The QAOA graph is only hidden statistically. What does that mean?**
Every qubit pair carries the same CX count, so counting CX per pair reveals nothing, but the graph is structure, so the view test cannot be identical across graphs [README, Honest limitations]. What we measured instead: commuting `rzz` runs are shuffled and decoys land at uniform boundaries, and an independent check over 800 locks found pair positions uniform (p = 0.62-0.93) and no difference between graphs (p = 0.69) [README, red-team finding 9].

**10. Can an attacker peel the decoys off?**
For lone-CX circuits, yes. Decoys are adjacent CX-block-CX pairs, so they hide the graph only when every real interaction is also such a pair, as QAOA's `rzz` is; where real interactions are lone CX, an attacker can peel the decoys off and read the real skeleton [README, red-team finding 12; `lock.py` docstring]. No demo secret lives in that skeleton: VQE's layout is the public ansatz, and Grover's skeleton is identical for every marked item.

**11. Padding grows as O(n²). Is that practical?**
Every one of the n(n-1)/2 qubit pairs gets the busiest pair's CX count: 6 pairs at 4 qubits, 190 at 20, 8,001 at 127 [README, Honest limitations]. In the scaling benchmark a 20-qubit QAOA shows 380 visible CX and compiles to 1,508 two-qubit gates, because far-apart pairs need SWAPs on heavy-hex [README, Scaling]. Cheaper padding is on the Round 2 roadmap.

## Threat model

**12. What if the same party compiles and runs the circuit?**
Then it sees the unlocked circuit: TrustPass still checks integrity and fidelity, but gives no confidentiality [README, Honest limitations]. Our threat model assumes the compiler is not the executor and never sees results [README, How TrustPass works].

**13. What about oracle-guided attacks (Zhang & Liu)?**
Out of our threat model, because the compiler never sees results, but we measured it: for a 2-qubit, 1-edge QAOA, a least-squares fit of all 18 key angles to the outputs of 6 random product-state inputs reproduced held-out inputs exactly and recovered (γ, β) = (0.79, 0.39) for the true (0.80, 0.40) [README, Honest limitations; Research gaps, row 3]. A defence and an attack suite on larger circuits are Round 2.

**14. You have only a few real hardware results. Why should we trust the numbers?**
Everything else runs on IBM fake backends with real calibration data, and the attacks are our own stand-ins modelled on the literature [README, Honest limitations]. We measured 179 circuits in 20 hardware jobs on ibm_fez, ibm_kingston and ibm_marrakesh over three days (2026-10-24, 26 and 28), each verified against the device's live calibration before it ran [README, Real hardware runs]: six runs of honest vs saboteur (and, in run 3, all five compilers) plus a 150-circuit transpiler-seed sweep. Pooled [README, Accuracy on real hardware]: 41/41 honest compiles accepted and 134/137 attacks rejected; 41 of 42 saboteurs measured worse on the device than the honest compile of the same lock (40 significantly, on 95% bootstrap intervals); QCEC caught every Trojan before it ran; and the 0.10 histogram test flagged 22 of 42 honest compiles and missed 30 attacks, so on hardware it cannot tell an attack from noise. The three misses are saboteurs the audit accepted on ibm_kingston on 2026-10-26 (ESP ratio 0.911-0.939, job dbfose8m94ac738u22t0); on the device they measured 0.945, 0.966 and 1.058 of their honest compile, inside the 10% tolerance. ESP overstated the saboteurs' loss on 37 of 42, and the noisy simulator was optimistic on 119 of 177 circuits (median gap 0.031). Three days and 3-4 qubit demos: the check pointed the right way on almost every circuit we ran, which still says little about how reliable it is across months or larger circuits.

**15. How do you know your hardware results are accurate?**
Three checks, none of which needed new jobs [README, Comparison with published results]. First, IBM's own data: from IBM's calibration archive for each job's date, the probability that no error occurs in the exact submitted circuit is 0.76-0.91 for our honest compiles with the device-wide medians and 0.86-0.93 with the published values of the qubits used, against measured 1-TVD of 0.52-0.96 (at or above the median-based estimate on 32 of 42, as expected for a no-error probability) [`bench/attested_device.csv`]. Second, other people's experiments: the same two-iteration 3-qubit Grover kept 61% and 68% of its ideal success probability on IBM's 2021 Falcon devices (Zhang et al., Quantum Inf. Process. 20, 233, Table 6), and 81% in our runs (median P(101) 0.762 of an ideal 0.945, 17 honest compiles), which fits Heron r2's 3-7 times lower published two-qubit error; for 4-node QAOA the only comparable result we found is a neutral-atom device (87% of ideal on another graph; ours 97%), and for the VQE ansatz we found none [`bench/attested_literature.csv`]. Third, our own predictions: the noisy simulator on the same calibration ranks all 177 predicted circuits with rank correlation 0.902 and a median gap of 0.031 [README, Accuracy on real hardware]. What this does not show: that the numbers will hold on other dates or larger circuits, or that our verdicts are right, which rests on the per-circuit results; and the comparisons are not like-for-like (device generation, shots, marked items averaged in Zhang et al.).

## Originality

**16. How is this different from split compilation and E-LoQ?**
Split compilation sends parts of the circuit to several compilers, or to one compiler at different times, so no single compile sees all of it; in TrustPass one compiler sees the whole locked circuit, the key keeps the angles secret, and the returned circuit is verified [README, Research gaps, row 9]. E-LoQ evaluates locking for concealment only, and nothing checks the circuit that comes back [README, Research gaps, row 1]. What we add is uniform per-pair CX counts, the secret-blind view test, and an audit against a free local compile that catches sabotage that stays equivalent [README, How TrustPass works].

## Live calibration

**17. Did the audit ever accept a saboteur?**
Yes, on live calibration. Our 4-of-4 results are on simulated IBM device models (90 matrices on FakeBrisbane and FakeTorino) [README, The detection matrix]. Against the live calibration of ibm_kingston on 2026-10-24, with no job run, the audit accepted the saboteur on QAOA (ESP ratio 0.921) and VQE (0.912): its qubits were only about 8-9% worse than the honest layout's, inside the 10% tolerance by design, while the other 43 of 45 verdicts across ibm_fez, ibm_kingston and ibm_marrakesh were as expected [README, Honest limitations; `bench/live_targets.py`]. It then happened on hardware: in job C on ibm_kingston (2026-10-26) the audit accepted all three saboteurs (ESP ratio 0.911-0.939), and the device measured them at 0.945 (Grover), 0.966 (QAOA) and 1.058 (VQE) of the honest compile of the same lock, so none lost more than the 10% we tolerate [README, Real hardware runs, run 5]. Across all 179 measured circuits these are the only three wrong verdicts. The audit flags compiles measurably worse than a free local compile; a saboteur that costs less than the tolerance gets through, and tightening it costs honest compiles: at a threshold of 0.95, 71 of 450 would be false rejects [README, Why 0.90 and 0.10].

## Robustness and speed

**18. Does any circuit parameter, decoy count or optimization level change a verdict?**
Not in our sweep. `bench/params.py` changed one parameter at a time on FakeBrisbane and FakeTorino: all 8 Grover marked items, 3 QAOA angle settings and 3 graphs, VQE reps and 3 weight seeds, decoys 0-2 and optimization levels 1-3. All 370 runs gave ACCEPT for honest and REJECT for every attack; saboteurs scored 0.397-0.819, the highest 0.081 under the 0.90 threshold [README, Parameter sweep]. Two caveats: `lock()` refuses VQE at reps 1 and 3 (an odd CX count per qubit pair it cannot pad), and the naive test alone passed 60 of 74 masked Trojans and 2 of 74 overt ones, which QCEC caught.

**19. How slow is it, and what costs the most?**
On one laptop the six steps up to the verdict (lock, compile, unlock, naive test, QCEC, fidelity audit) take 0.16-0.48 s per compile and a full detection matrix a median 0.7-1.0 s [README, Timing; `bench/timing.py`]. Scoring takes 95% of all measured time, nearly all of it the confidentiality score's 30 wrong-key guesses, and 2 decoys roughly double to triple the total. In gates, decoys are also the expensive knob: at 2 decoys QAOA compiles to 54-60 two-qubit gates instead of 16 [README, Parameter sweep].
