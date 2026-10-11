# Draft ordered-conversation smoke

These are source-checked development cases, not a reviewed nightly gate or a
general-memory benchmark. Run this two-question dataset with `capture
--conversation`; run `../financial-conversation-reset` separately to create a
fresh conversation. Never combine the reset case into the original chat.

Use an existing, verified, dedicated public FinQA workspace. Reuse its complete
source-label mappings in a new local manifest whose dataset name/version match
each dataset. Do not run `prepare`: these directories intentionally contain no
duplicated corpus or expected-answer documents.

Independent reference: FinQA revision
`0f16e2867befa6840783e58be38c9efb9229d742`, PM 2017 excerpt page 38,
source SHA-256
`f4d992784b64c3c93b3725ab4dad90cd75c51cda2b7aa0855f30fd1b44e72115`.
The excerpt states RRP net revenues **excluding excise taxes** of $3.6 billion
in 2017 and $733 million in 2016. Answers need the correct year, financial
concept, value/unit and active citation to this source. The reset case must
clarify without citations/provider calls, not recall an unrelated conversation.

Capture records expose observed context policy/mode and usage, but the existing
offline scorer does not automatically judge conversation transitions or these
financial value/unit checks. Validate them separately; never claim a generic
scoring pass qualifies multi-turn quality. External human rubric review,
broader workloads, source changes, memory budgets and nightly activation remain
under #74/#62/#75/#82/#53. No accepted baseline is changed here.
