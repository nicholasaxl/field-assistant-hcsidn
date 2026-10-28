# Accuracy scorecard

Run on 2026-10-28 with `qwen2.5:3b` and `nomic-embed-text`.
Corpus: 8 documents, 44 passages (the packaged sample library, not live use).
Questions: 21 in scope, 6 unrelated, 5 safety, 3 error codes.

| Measure | Result |
|---|---|
| Answers that pass (right document, right content, not refused) | 90% |
| Right document in the top 4 passages | 100% |
| Right document ranked first | 90% |
| Unrelated questions refused | 83% |
| Steps traced to a source | 87% |
| Safety alerts raised when required | 100% |
| Error codes matched exactly | 100% |
| Median time to answer | 29.8 s |

## Questions that failed

- (in_scope) Kiosk card reader gives repeated read errors
- (in_scope) Which firmware version needs a Rev C card reader?
- (out_of_scope) How do I change the Wi-Fi password on my home router?

Small test set: treat these as a regression guard and a rough indicator, not a guarantee. Re-run after changing documents, settings or code.
