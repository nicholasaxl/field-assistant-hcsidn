# Accuracy scorecard

Run on 2026-10-28 with `qwen2.5:3b` and `nomic-embed-text`.
Corpus: 8 documents, 44 passages (the packaged sample library, not live use).
Questions: 21 in scope, 6 unrelated, 5 safety, 3 error codes.

| Measure | Result |
|---|---|
| Answers that pass (right document, right content, not refused) | 95% |
| Right document in the top 4 passages | 100% |
| Right document ranked first | 95% |
| Unrelated questions refused | 100% |
| Steps traced to a source | 94% |
| Safety alerts raised when required | 100% |
| Error codes matched exactly | 100% |
| Median time to answer | 4.3 s |

## Questions that failed

- (in_scope) Which firmware version needs a Rev C card reader?

Small test set: treat these as a regression guard and a rough indicator, not a guarantee. Re-run after changing documents, settings or code.
