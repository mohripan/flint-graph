# M31 editor and preview implementation plan

Scope/standing authorization: [focused design](../specs/2026-10-27-narrative-editor-preview-design.md),
GitHub #123; #122 API is delivered and closed after green CI/native/HTTP proof.

1. Add failing public editing/transport tests, then bounded draft helpers, source
   types, API client calls and scene/character/variable/condition form operations.
2. Build the additive Studio collection/writing desk/map/history with explicit
   unsaved/retry/conflict state, permission handling and safe navigation/cleanup.
3. Add failing protocol/validator tests, then the trusted static preview adapter,
   explicit pinned build tool and separate-host local server/CSP/message channel.
4. Embed validated revision playtesting with matching acknowledgment, timeout and
   Escape/focus lifecycle. Prove actual shared Godot execution and cookie/token
   isolation in the browser, not a second JavaScript interpreter or static image.
5. Live browser author/save/preview/reopen/conflict/keyboard/mobile checks; retain
   screenshots and reports, review, run required gates, commit/push and close only
   after green CI. Continue #124 release design afterward.

No hosted arbitrary-code compilation, provider activation, asset upload, release
publishing or old corpus migration is included. Use the existing one review agent.
