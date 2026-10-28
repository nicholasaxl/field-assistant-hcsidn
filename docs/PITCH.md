# Field Assist: pitch notes

Field Assist answers troubleshooting questions for ATM, POS and kiosk engineers from the company's own manuals and runbooks. It runs entirely on the engineer's machine: no cloud, no per-question fees, no data leaving the building. This page is for the person presenting it: the claim, a demo you can run in about six minutes, the numbers, and the limits to say out loud before anyone asks.

## The claim, stated honestly

Field Assist **reduces how often a person has to stand by for routine, documented faults**. It does not diagnose faults nobody has written down, and it should not decide anything about cash, keys or tampering. Say "cut standby coverage and escalations", not "replace the standby team".

## Before you present

1. Ollama is running (it starts with Windows). Start the app with `.\start.ps1` and open http://localhost:8000.
2. Wait for **Model ready** in the header. The first question after a long idle can take 20 seconds while models load; ask one throwaway question first.
3. Library should show the sample documents. Insights should be empty, or showing sample data with its amber banner. Never present sample numbers as results.
4. Close other heavy applications. On a CPU-only laptop, answers that need the model take 10 to 25 seconds.

## Demo script (about six minutes)

| Step | Do this | Say this |
|---|---|---|
| 1. A documented fault | Choose **HX-ATM-500**, ask *How do I clear a note jam in the ATM dispenser?* | "Two seconds. These are the runbook's own steps, copied word for word, no model involved. Every step has a ring: filled means a document contains it." Click a citation chip, then **Open the document**. |
| 2. An error code | Ask *I'm getting P-1002 on the terminal* (device **All devices**) | "Error codes are looked up exactly in the table, then the runbook adds the procedure. It narrowed to the POS on its own; this note says so, and one tap searches everything." |
| 3. Safety | Ask *ATM shows A-2002* | "A suspected card skimmer. The alert comes from a rules file you control, not from the model, and the procedure stays hidden until it has been read." |
| 4. It knows what it doesn't know | Ask *What is the capital of France?* | "Within a couple of seconds it says it can't find this, rather than inventing something. Then it offers a handoff summary." Click **Escalate with a summary** and show the text. |
| 5. Follow-up | After step 1, click **That didn't work** | "It remembers the last three turns, won't offer the same passage twice, and flags anything the documents don't support." |
| 6. Guided mode | Click **Guide me step by step**; press **Done**, then **Didn't work** | "One step at a time. A failed step is saved, so we learn which steps fail in the field, and it leads straight to a handoff." |
| 7. A vague question | Ask *help* | "It asks which device instead of guessing." |
| 8. Insights | Open **Insights**, then **Preview with sample data** | "These numbers are invented and labelled. In real use this fills from the Fixed it and Didn't fix it buttons. The time saving is an estimate: answers fixed times the minutes you set." Point at **Gaps in the library** and **Steps that fail most**. |
| 9. It adapts | Open **Library**, drop in `data/upload_demo/pos_customer_display_flicker.md`, choose HX-POS-200, then ask *The customer display flickers during a sale* | "A new document is searchable in seconds. No training." |

Remove the sample data afterwards (Insights, then **Remove sample data**).

## What the numbers say

Measured on 28 October 2026 with `qwen2.5:3b` and `nomic-embed-text`, end to end, on a CPU-only laptop. The full run is in [scorecard.md](scorecard.md); the starting point is in [scorecard.baseline-m1.md](scorecard.baseline-m1.md).

| Measure | Starting point | Now |
|---|---|---|
| Answers that pass (right document, right content, not refused) | 90% | **95%** |
| Right document ranked first | 90% | **95%** |
| Unrelated questions refused | 83% | **100%** |
| Steps traced to a source | 87% | **94%** |
| Safety alerts raised when required | 100% | 100% |
| Error codes matched exactly | 100% | 100% |
| Median time to answer | 29.8 s* | **4.3 s** |

\* The starting-point time was measured while other work was using the machine, so it overstates the improvement. The honest picture: documented numbered procedures now come back in 0 to 2 seconds with no model call, and answers the model has to write still take roughly 8 to 30 seconds.

One of 21 in-scope questions still fails (which firmware version needs a Rev C card reader). It is a table lookup the small model gets wrong, and it is listed in the scorecard rather than hidden.

The test set is 35 questions over 8 synthetic documents. It is a regression guard and a rough indicator, not a promise about your real manuals.

## Say these limits before anyone asks

- **It only knows what is in the documents.** A fault nobody wrote down gets "not found, escalate", by design.
- **Small local model.** It runs on a CPU, so some answers take 10 to 25 seconds. Documented procedures with a close match come back in seconds because no model is involved.
- **Untested on your real manuals.** Everything above is the sample library. Scanned PDFs are not read, and the search model is English-leaning, so test ten real questions in your own language before committing.
- **Follow-ups are shallow on purpose.** Three turns of memory, handled by rules. It will not hold a long conversation.
- **No login and no multi-user support.** It is a single-machine prototype.
- **The time-saved figure is an assumption you set**, not a measurement.

## Likely questions

**Will it give a wrong answer?** Sometimes. That is why every step shows its source, untraceable steps are flagged, Critical faults always escalate, and the scorecard lists what failed. The pilot below measures it on your data before anyone relies on it.

**Where does our data go?** Nowhere. Models, documents and the feedback log all stay on the machine (`data/feedback.db`).

**What does it cost?** No per-question or licence cost: the models are free and run locally. The costs are the machine and the time to curate documents.

**Can it call a person or open a ticket?** Not yet. It produces a handoff summary to copy into your ticketing tool; integration is a next step.

**Why not a bigger model?** It would answer unusual questions better and faster on suitable hardware. This prototype deliberately shows what is achievable at zero cost.

## Suggested pilot

1. Load your real manuals, runbooks and (best of all) resolved tickets of the form "symptom, what fixed it".
2. Run for four to eight weeks **alongside** the current standby arrangement, in shadow mode.
3. Judge it on its own Insights: the fixed rate (and how many answers got a response), the gaps list, the steps that fail most, and a scorecard built from 50 to 100 real past questions.
4. Reduce standby coverage only for the fault categories where it clearly performs, and keep a person on call for the rest.
