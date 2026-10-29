# TrustPass: demo video script (about 2:45, limit 3:00)

**Rules this script is built to meet:**
- Your own voices. No AI or text-to-speech narration, and no avatars.
- Under 3 minutes.
- The architecture explained by team members.
- Circuits actually running.

**Speakers:** four speakers, S1–S4. With 3 people, S4's lines go to S1. Read naturally; the numbers below are real (Grover, FakeBrisbane, seed 7).

Live runs vary a little each time, because the lock is freshly random. **If a number on screen differs slightly, say the one on screen.**

---

## Before you record (5 min)

1. **Live server.** Open PowerShell and run these two lines, one at a time:
   ```powershell
   cd "D:\Claude does stuff\QHack-India\trustpass"
   .\.venv\Scripts\python.exe server.py
   ```
2. **Browser.** Open http://localhost:8600 in Chrome. Press F11 for full screen; a 1920×1080 screen is ideal.
3. **Warm-up.** Turn the SOURCE knob through every position once, so the first live runs are already done.
4. **Second terminal.** Open a second PowerShell window, `cd` to the same folder, and make the font big: Ctrl and the mouse wheel.
5. **Diagram.** Keep the architecture diagram ready. Use the README on GitHub (it renders the flowchart) or the architecture slide from your PPT.
6. **Recorder.** Use Xbox Game Bar (Win+G, then record) or OBS. Record the screen first and talk over it, or talk live: either is fine. If a knob turn takes a few seconds, keep talking or trim the wait in editing.

---

## The script

| Time | Who | On screen | Say this |
|---|---|---|---|
| 0:00–0:12 | S1 | The full TrustPass panel, red REJECT lamp lit. | "Hi, we're team ___. This is TrustPass: it lets you send a quantum circuit to a compiler you don't trust, and still check what comes back before you run it." |
| 0:12–0:38 | S1 | Stay on the panel. Point at the display, then the SOURCE knob. | "Quantum circuits must be compiled for a specific chip, and more and more that step runs someone else's code: transpiler plugins and cloud compile services. That code sees your whole circuit. It can steal it, plant a Trojan that changes the answer, or do what only quantum hardware allows: return an identical circuit parked on the noisiest qubits. The usual histogram check catches the obvious Trojan and little else." |
| 0:38–1:08 | S2 | **Architecture diagram** (README flowchart or your slide). Point at each box as you say it. | "Five steps. One, **lock**: on our machine, every single-qubit angle becomes a key symbol, and decoy gate pairs make every qubit pair look equally connected. Two, the **untrusted compiler** sees only that locked circuit. Three, **unlock**: back on our machine, we put the key back. Four, **verify**: MQT QCEC formally proves it computes the same thing on every input, and a fidelity audit checks its estimated success against a free honest compile. Five, **score**: accept only if both pass; only then does it go to the hardware provider." |
| 1:08–1:25 | S2 | Back to the panel. Point at the header "What the compiler sees: 153 key angles · 0 numeric". Scroll down to **Inspect the circuit**, press **YOUR CIRCUIT**, then **WHAT THE COMPILER SEES**, and point at "8 different secrets → 1 identical view". | "This is all the compiler gets for our Grover circuit: 153 key symbols and zero real angles. Our secret is the marked item. We locked the circuit with all 8 possible secrets using the same lock randomness, and the compiler saw the exact same circuit every time." |
| 1:25–1:38 | S3 | Scroll back to the top. Turn **SOURCE** to **HONEST**. The keys light up one by one, then three PASS readouts and a green ACCEPT. | "Now the attacks, running live on a 127-qubit IBM device model. An honest compile: equivalent, and as good as a free compile. Accept." |
| 1:38–1:52 | S3 | Turn **SOURCE** to **TROJAN DORMANT**. Point at CH1 still showing **PASS**, CH2 **FAIL**, and the red REJECT. | "A dormant Trojan does nothing on the usual all-zero input, so the histogram test passes it. The equivalence proof covers every input, and it catches it." |
| 1:52–2:12 | S3 | Turn **SOURCE** to **SABOTEUR**. Point at CH1 PASS, CH2 PASS, CH3 FAIL, "ESP 0.389 vs 0.710", and the caption under the lamp. Then scroll to the CH3 histogram and point at the bars for **101**. | "The hardest one: a saboteur. Its circuit really is equivalent, so even the proof passes. But it's parked on qubits with 6% readout error against a 2% median. Its estimated success is about half an honest compile's, so the audit rejects it. On the noisy simulator, the right answer drops from 66% to 31%." |
| 2:12–2:22 | S3 | Scroll back up to the **Detection matrix**. Point at the counters **1/4** and **4/4**. Flip **BACKEND** to TORINO; leave CIRCUIT on Grover. | "Across all five compilers: today's histogram check catches one attack in four here. TrustPass catches all four, on every circuit and simulated IBM device model we tested. On the live calibration of a real device, ibm_kingston, the audit did accept a milder saboteur, eight to nine percent worse: inside its ten percent tolerance, by design." |
| 2:22–2:37 | S4 | **Terminal.** Run `.\.venv\Scripts\python.exe demo.py --matrix --backend FakeTorino` and let the table print. Optionally run `.\.venv\Scripts\python.exe test_trustpass.py` and show "0 failed". | "The same pipeline from the terminal: the circuit is locked, compiled for a 133-qubit Heron device model by all five compilers, unlocked and verified. Same result: one in four versus four in four. Our fifteen tests pass in under twenty seconds." |
| 2:37–2:50 | S4 | The rating plate at the bottom of the page, or your roadmap slide. | "We also attacked our own tool: fifteen findings, each fixed or documented, and we state its limits openly. Next: repeated real-hardware runs, larger circuits, and a Qiskit transpiler plugin. TrustPass: compile anywhere, check before you run." |

Live demo only (not in the video): scroll to **Plant a Trojan**, let a judge pick gate, qubit and position, press **PLANT + VERIFY**, and point at CH2 FAIL and REJECT.

Live demo with `server.py --allow-ibm`: press **SUBMIT TO IBM** early (queue time is unpredictable) and come back to its result at the end; if it is still queued or fails, show the recorded **Measured on real IBM hardware** table instead.

That's about 440 spoken words, roughly 2:45 at 160 words a minute. Rehearse with a timer: 3:00 is a hard limit. If you run long, shorten the 0:12–0:38 problem line first.

---

## Words to avoid (judges will check)

- Say "**checks** it's not sabotaged", not "proves". The fidelity audit uses a threshold. Only the equivalence check is a proof.
- Say "on a **127-qubit IBM device model**" or "**simulated** IBM device with real calibration data", never "on real IBM hardware": the demos in the video are simulated. Our hardware results are 121 measured circuits in 13 jobs on ibm_fez, ibm_kingston and ibm_marrakesh over three days (2026-10-24, 26 and 28; 50 more on ibm_kingston still queued); if you mention them, say "three days, small circuits" (every judged honest compile accepted, every attack rejected, every saboteur measured worse on the device).
- Say the compiler "learns nothing **about the angles**", not "learns nothing".
- The QAOA graph is hidden **statistically**, not perfectly. If asked, that's in the README limitations.
