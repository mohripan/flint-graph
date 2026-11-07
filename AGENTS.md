# Agent Handoff Guide

## Studio architecture and delivery

FlintGraph is an authored visual-novel Studio with Godot/GDScript export.
Read `docs/product/narrative-game-studio.md`, ADR 0035 and the Studio section
of `docs/ROADMAP.md` before selecting work. Studio milestones define the delivery
order; shared-service contracts and security invariants remain valid.
The M30 written spec was approved for implementation on 2026-10-27;
the user authorized one review sub-agent and autonomous continuation. Preserve
the unrelated uncommitted #109 trace-probe work; do not stage, discard or resume it
as part of Studio work. M30 package loading, reference playback/saves and
Godot source export/player and real browser qualification are delivered.
M31 #123 studio editor and isolated local Godot preview are live qualified with
green CI/container smoke. #124 now has qualified ledger/lifecycle APIs, execution
fences/private input loading, bounded USTAR/ZIP codecs, explicit Linux image
preparation, trusted Godot child/watchdog and standalone host runner. Actual
PostgreSQL recoveries, native export/tamper rejection, absent-worker watchdog and
real host-task cancellation passed. Read the M31 progress/release contract and
`docs/reports/2026-10-30-narrative-build-runner.md` plus linked child/execution
reports for exact scope. Immutable storage/publication and authorized downloads
are now qualified too (real MinIO, PostgreSQL and17 HTTP calls with actual engine
build/downloaded-source import): read `docs/reports/2026-10-30-narrative-release-publication.md`.
The relay/workflow/activities now pass connected real Temporal/PostgreSQL/Godot/
MinIO/authorized-download qualification; see
`docs/reports/2026-10-30-narrative-temporal-worker.md`. Separate operator worker/
relay processes, periodic closed-run recovery and fair bounded expired cleanup
now have real process-kill/restart, active-cancel/retry and natural-expiry proof:
`docs/reports/2026-10-30-narrative-build-recovery.md`. Owned worker/relay receipts
are in ignored `notes/narrative-worker-owned.json` / `narrative-relay-owned.json`;
preserve their private root/queue across restarts. The Studio Releases dialog and
the live author→save→build→download→play proof complete #124/M31:
`docs/reports/2026-10-30-narrative-releases-ui.md`. That proof found that build
children need a bounded writable `/tmp`; otherwise Godot packs an empty
`project.binary` and the browser build black-screens. The host now requires the
`/tmp` tmpfs and rejects such packs. The owned local API admits releases with the
existing builder pins. Preserve private owned fixtures.
On 2026-10-30 the user made chat-driven creation the primary workflow
([ADR 0038](docs/adr/0038-conversational-authoring-through-reviewed-proposals.md),
#168): a Studio Assistant panel proposes bounded story edits that become revisions
only on acceptance. It runs as fenced Temporal jobs via the opt-in
`narrative_assistant_worker` with local Ollama by default; read
`docs/reports/2026-10-31-narrative-assistant.md` and
`docs/runbooks/narrative-assistant.md`. The owned assistant worker receipt is
`notes/narrative-assistant-owned.json`. #171 moved the assistant to a full-page
Studio view whose turns stream steps, thinking and reply text from durable
PostgreSQL events (migration 0023, IDs-only Temporal history); Ollama `think` is now
explicit and budgeted. Read `docs/reports/2026-10-31-assistant-live-turns.md`.
On format 2 the assistant (prompt v2) edits sprites, framing, colours, stage nodes,
expressions and the theme, uses library files by ID, and suggests image jobs that
the creator starts with Generate: `docs/reports/2026-10-31-assistant-v2-tools.md`.
Prompt v3 asks for missing character names, outfits and image intent before proposing;
transparent sprites default to high resolution. Accepted image suggestions now resolve
to durable server jobs by proposal ID and original operation index. Assets discovers
background jobs across views, and inherited stage image pickers show their effective
images. Read `docs/reports/2026-10-31-assistant-image-actions.md`; no migration or runtime
bump is involved. Existing owned API/assistant processes need an owner-managed reload
to use the new endpoints/prompt; never restart another session's processes.
Expressions (ADR 0041 slice A, migration 0026) repaint only the face of an approved
base sprite as `character_expression` image jobs, so expressions swap on stage without
jitter; read `docs/reports/2026-10-31-character-expressions.md`. Poses (slice B) use
the opt-in pinned FLUX.2 klein 4B editing worker
(ADR 0048, migration 0035): immutable reviewed look + pose instruction, then
manual comparison/approval and normal stage binding. Read
`docs/reports/2026-11-01-character-poses.md` and the image-generation runbook.
The Studio launcher selects the separate `pose` service explicitly. ADR 0049
(migration 0036) adds one approved supplemental view, frozen source snapshots,
protocol-1 compatibility and explicit primary-rendering instructions. The operator
sets `NARRATIVE_POSE_MAX_REFERENCES=2` after qualification; the default is one.
Read `docs/reports/2026-11-01-pose-reference-views.md`. Identity, outfit and drawing
style/lighting are separate review dimensions; the new flow does not lock style.
Slice C (migration 0030) draws event CGs of one or two characters from an approved
image of each through a pinned IP-Adapter Plus (ViT-H): Assets → CGs → Generate CGs,
`scene_art` image jobs, opaque 1344×768 candidates. The image worker needs the optional
`FLINT_GRAPH_NARRATIVE_IMAGE_IP_ADAPTER_*` pin; read `docs/reports/2026-10-31-scene-art-cgs.md`.
Two-character CGs are experimental (7 of 12 seeds keep both looks; eight candidates per
Generate); M40 #185 owns improving that baseline.
Downloaded local generation models
(Animagine XL 4.0, Kokoro-82M, ACE-Step 3.5B) are verified under ignored
`notes/models/`; runtime availability is qualified individually in the reports below.
The Studio rail is a
Godot-style scene hierarchy (#169): scenes are line chains projected from the node
graph, folders live in an editor-only versioned layout (migration 0021), and a
script editor edits a whole scene. Long-form limits (10k nodes / 5 MB) are #172;
read `docs/reports/2026-10-31-scene-hierarchy.md`. Character creation (#170 first
slice, ADR 0039, migration 0022) generates portraits locally with Animagine XL 4.0
through the opt-in `narrative_image_worker` and an isolated child in
`runtimes/imagegen` (its own uv lock, CUDA 12.8); read
`docs/reports/2026-10-31-character-creation.md` and
`docs/runbooks/narrative-image-generation.md`. Portraits are editor metadata;
binding approved images to story assets puts them in playtests and releases.
The owned image worker
receipt is `notes/narrative-image-owned.json`. ADR 0040 plans the visual novel stage,
theme and story package v2 in four slices. Read the design's "Review changes"
section before starting slices 2–4. Slice 1, the asset library (uploads with rights
declarations and generated backgrounds, migration 0024), is delivered; read
`docs/reports/2026-10-31-asset-library.md`. Slice 2, story package v2, is delivered
with `narrative_package_v2_enabled`: the format, reference player,
saves, asset binding by SHA-256, server-built NOTICES and the explicit upgrade. Read
`docs/reports/2026-10-31-story-package-v2.md`. Slice 3 (runtime 0.3.0) plays v2
everywhere: Godot `vn_view.gd`, playtests with transferred asset bytes and a revision
asset endpoint, and release builds with assets; read
`docs/reports/2026-10-31-vn-stage-runtime.md`. Slice 4 (Studio editors: Look tab, scene
stage panel, line expressions, character sprites, upgrade button) completes ADR 0040; the
flag now defaults on and new projects start on v2. Read
`docs/reports/2026-10-31-vn-studio-editors.md`; editor logic is in
`frontend/src/narrative/stageModel.ts`. Runtime 0.4.0 adds stage framing (character size and
top, free horizontal placement); read `docs/reports/2026-10-31-stage-framing.md`. Character jobs can
ask for high resolution (2× hires fix: Lanczos upscale plus a light img2img repaint, migration 0027,
on by default for sprites); read `docs/reports/2026-10-31-high-resolution-sprites.md`. Owned playtests need
`VITE_FLINT_GRAPH_PREVIEW_ORIGIN` on the frontend dev server.
The whole local Studio now starts with `uv run python tools/narrative/studio.py`
(API, four workers, playtest server, frontend), configured by the git-ignored
`studio.local.env` (template `tools/narrative/studio.env.example`; this machine's copy
holds the owned fixture settings, so never print it). It replaces the
`notes/narrative_owned_process.py` and `notes/serve-main-studio-api.py` starts. The owned PostgreSQL, MinIO and Temporal
fixtures now use Docker volumes with fixed ports
(`notes/persist-narrative-fixtures.py`). The earlier tmpfs fixtures lost all data on
a Docker restart.
Runtime 0.5.0 adds event CG overlays and an independent local gallery (#161 presentation,
[ADR 0042](docs/adr/0042-event-cgs-and-gallery.md)). Format 2 stage nodes use optional
`cg` (image ID, null clears); saves missing it load null. Gallery unlocks persist by
story ID outside slots in exports and stay in memory in playtests. The Studio stage
panel picks CGs and previews the overlay; Assets → CGs browses and uploads the image
library with a dedicated CG panel. See
`docs/reports/2026-10-31-event-cgs.md` for parity, private builder/preview and real
release qualification. CG generation from a character's approved image is ADR 0041 slice C.
[ADR 0043](docs/adr/0043-asset-folders-and-line-voices.md) adds editor-only asset folders
(migration 0028; automatic groups by kind and character) and voiced lines on runtime 0.6.0
(0.6.1 plays the first voiced line in playtests and adds a web start screen when sound is blocked):
format 2 `audio` assets (canonical WAV) and an optional line `voice` (full or a
vocalization such as "fufu"; silent by default), played by all four implementations with a
player Voice slider. Clips come from Kokoro-82M on the GPU (CPU fallback) through the opt-in
`narrative_voice_worker` and the isolated `runtimes/voicegen` child (migration 0029; a
Kokoro voice per character profile), or from WAV uploads. Read
`docs/reports/2026-10-31-asset-folders-and-line-voices.md` and
`docs/runbooks/narrative-voice-generation.md`; the launcher's `voice` service needs the
voice settings in `studio.local.env`.
[ADR 0045](docs/adr/0045-expressive-and-cloned-character-voices.md) (M39, #173–#178) adds
cloned and expressive voices: a code catalog of Chatterbox (English, Turbo, Multilingual V3;
MIT, PerTh watermark), Qwen3-TTS 1.7B (cloning, stock voices; Apache-2.0) and IndexTTS-2.5
(bilibili license with duties on audio; IndexTTS2 is excluded for its CC-BY-NC MaskGCT codec)
beside Kokoro, installed by `FLINT_GRAPH_NARRATIVE_VOICE_MODELS` with pinned manifests
(`tools/narrative/fetch_model.py`) and run by isolated `runtimes/voicegen-{chatterbox,qwen3,indextts}`
children (protocol 2). Private voice references with a consent declaration (migration 0031),
a model plus stock voice or reference per character, per-line delivery defaulting from the
expression (editor metadata, not story format), per-workspace license acceptance by hash
(migration 0032), NOTICES with license texts and a player-terms block, and runtime 0.7.0's
one-time player license screen. Read `docs/reports/2026-11-01-expressive-and-cloned-voices.md`
and the runbook's ADR 0045 section; weights live under ignored `notes/models/`.
M31 #122 adds authorized immutable text revisions
with recoverable conflicts; read `docs/milestones/31-authored-narrative-studio.md`
and the M30 report for actual progress before claiming a complete authoring product.

Prompt management now uses a typed catalog and reviewed complete lock (ADR 0044,
#135–#137), with an optional isolated digest-pinned Langfuse 4.72.0 profile and
SDK 4.15.0 generated read API. See `docs/runbooks/prompt-management.md` and
`docs/reports/2026-11-01-langfuse-prompt-migration.md`. Migration 0033 pins generic
bundle manifests on runs/jobs; keep nullable historical identities unknown and
never replay a missing referenced bundle using current defaults. Provider/assistant
wording and default image policy/conditioning live in `prompts/prompts.lock`;
version every authored change, preserve history, and use CLI check against the Git
base. Runtime keys are Viewer-only; author/release keys and tenant inputs never
enter prompt refresh. Default is locked/offline. Do not enable SDK tracing or
restart owned services to activate a new lock. The legacy image TOML is an explicit
locked-mode override, never an automatic source to publish.

M40 #180–#186 has an isolated character-preservation research bench and the first
Studio look/feedback slice described below. Read ADR 0046,
`docs/reports/2026-11-01-character-preservation.md` and
`docs/architecture/character-preservation-research.md`. Staged FLUX.2 klein 4B
followed 16/16 primary pose requests on two original adult fixture characters on
the 12 GB GPU; it is the next pose candidate. Cached ControlNet reproduced all
16 baseline PNGs with lower memory. Two-reference editing is promising, but
adding a background reference changed hair in one of two scenes. Identity scores
do not certify clothes or reviewed traits; the provisional garment fit missed
14/15 labelled drifts. Agent labels are not creator calibration. CCIP's exact
weight license remains unresolved. The initial research delivery measured LoRA memory on random tensors;
ADR 0050 below adds real private project-style training and pose integration.
Creator-calibrated quality and character-specific training remain separate.
Use the separate `runtimes/character_eval` / `runtimes/character_lab` locks; never
add these dependencies or private weights to the API, Studio workers or games.
ADR 0047 and `docs/reports/2026-11-01-reviewed-character-looks.md` deliver immutable
looks, explicit default selection, frozen Studio portrait/expression/CG admission,
optional isolated WD-only CPU suggestions/comparison, and manual candidate
feedback/badges (migration 0034). It loads no CCIP weights and activates no
automatic thresholds/ranking. Original assistant image APIs remain profile-based;
keep their integration separate. Owner-managed migration/API/frontend reload is
needed; never restart owned services. Qualified person assignment, pose-model
rollout are delivered by ADRs 0048/0049 below; character-specific training and
creator-calibrated quality remain follow-up work. Do not close
all seven issues from these reports.

Studio stage analysis now propagates to a complete fixed point without an
iteration cutoff. It uses iterative reverse postorder, a de-duplicated FIFO and
structural joins; it still conservatively merges all structural routes, without
evaluating conditions. General and narrative API rate pools both have bounded,
expiry-ordered storage and hashed pre-auth identities. The new general cap is
`rate_limit_max_buckets`; neither pool is a replica-wide quota. See
`docs/reports/2026-11-01-stage-propagation-and-rate-limits.md` and deployment
hardening for the correctness regression, scope and exact verification commands.
The assistant API stream re-reads events after observing terminal status so a
concurrent finish cannot close the stream before its final event is drained.

ADR 0054 (migration 0041) adds opt-in **Repair area…** on completed pose candidates.
It freezes the source/region and inherits the original trained versions. Protocol 5
uses the target plus approved look, then composites only the selected patch; an
independent parent PNG decoder rejects outside pixel, alpha, canvas or crop changes.
Deploy API/pose worker together with `NARRATIVE_POSE_MAX_REFERENCES=2` before enabling
`NARRATIVE_POSE_REPAIRS_ENABLED` (default off). Approval/anatomy review stay manual.
Read `docs/reports/2026-11-02-pose-region-repairs.md` and the image-generation runbook.

Public pages and invite-only access ([ADR 0058](docs/adr/0058-invite-only-access-and-usage-limits.md),
migration 0043): `/` main page, `/how-it-works`, `/join`, and the Studio at `/studio`
(old `/?project=` links still work). `FLINT_GRAPH_ACCESS_MODE=invite` gates every
current-user API on an access grant redeemed from a hashed invitation key or an email
invitation (verified address); operators come from `FLINT_GRAPH_ACCESS_ADMIN_EMAILS` or the
OIDC admin group. Per-user image/voice/assistant/release/training limits are charged by
`charge_usage` in each job's admission transaction after its idempotency check; add it to any
new paid job path. Default `open` mode is unchanged. Read
`docs/runbooks/invite-only-access.md` and
`docs/reports/2026-11-06-main-page-and-invite-only-access.md`.
[ADR 0059](docs/adr/0059-credits-and-unlimited-access.md) (migration 0044) adds credits:
`charge_usage(item=…, units=…, quantity=…)` checks the per-kind caps, then spends
`price × quantity` from the grant's balance (402 `out-of-credits`) and writes `credit_ledger`.
Prices are the code table `application/credit_prices.py` (override with
`FLINT_GRAPH_ACCESS_CREDIT_PRICES`); a new paid path needs a price item there and the
mirrored rule in `frontend/src/site/creditsModel.ts`. Invitations and grants can be unlimited;
operators adjust balances with an audited note. Read
`docs/reports/2026-11-06-credits-and-unlimited-access.md`.

[ADR 0060](docs/adr/0060-assistant-thread-event-log.md) (migration 0045) makes an assistant
conversation a fold over the append-only `narrative_assistant_thread_events`, modelled on
Capsulet's durable runtime. Write lifecycle changes with `append_thread_event` in the same
transaction, and declare new kinds in `narrative/assistant/log.py`. The fold
(`fold_thread`) is the only source of model history and of the Studio's **Activity log**;
turn rows stay the operational ledger for fencing, and a test asserts the fold agrees with
them. The database refuses `UPDATE`/`DELETE` on the log. Read
`docs/reports/2026-11-06-assistant-thread-log.md`.

[ADR 0061](docs/adr/0061-assistant-runs-generation.md) (migration 0046, prompt v4) makes the
assistant really generate: sprites, backgrounds, expressions, CGs and voices, with results and
Approve/Use in the chat. `narrative_assistant_actions` is the ledger; `dispatch_actions` and
`reconcile_actions` run in the assistant worker, so nothing needs an open page, and the
worker therefore needs the API's image, voice and object-store settings. The output schema has
one exact shape per operation, and `response_schema()` orders it (`reply`, `op`, `type` first):
Ollama's grammar writes fields in schema order, and the lock's sorted keys funnelled the model
into `set_title`. New story fields the model may write must be added to that schema too. Read
`docs/reports/2026-11-06-assistant-generation.md`.

[ADR 0062](docs/adr/0062-attach-library-items-to-assistant-messages.md) (migration 0047, prompt
v5) adds the composer's Library: characters and approved files attached to a message, frozen on
the turn, described to the model under the IDs it must use, and always offered regardless of
the 120-file limit. Assistant thinking is now off by default: with the exact grammar it made turns
about 14 times slower without more right answers. Exact line shapes require a spoken line's
speaker. Read `docs/reports/2026-11-06-assistant-library.md`. Separation between people comes
from sign-in, not invitation keys: `dev` auth makes everyone one user, and an owner of any
workspace they name, so never expose it (`tests/integration/test_narrative_assistant_isolation.py`).

[ADR 0063](docs/adr/0063-assistant-child-sessions.md) (migration 0048, prompt v6) adds child
sessions: conversations one level under a parent, started from the chat header or by the
`start_child_session` action, which queues through the action dispatcher. The operation is absent
from the grammar inside a child, because a prompt rule alone did not stop the model delegating
instead of working. Parents and children stay connected through `child.*` log events and
`child_context`. Read `docs/reports/2026-11-06-assistant-child-sessions.md`.

[ADR 0064](docs/adr/0064-standard-player-controls.md) (runtime 0.8.0) adds backlog, auto-advance,
skip-read, text speed, hide, quick save and speaker focus to `vn_view.gd`, with pacing in
`runtime/reading.gd`. They never touch story state, so format, saves and the reference player are
unchanged. Text appears over time by default, so native UI probes that press once per line call
`_set_text_speed("instant")` first. Save, Load and the rest moved into a Menu panel. After a runtime
change the launcher rebuilds the playtest and release builder itself, into `notes/studio-builds`.
Adding a runtime file means updating `pyproject.toml`, `export/__init__.py`, `build_child.py` and
`build_preview.py`. Read `docs/reports/2026-11-07-player-controls.md`.

[ADR 0065](docs/adr/0065-stage-transitions-and-effects.md) (runtime 0.9.0, prompt v7) adds closed
`transition` (cut, fade, dissolve, slide) and `effect` (shake, flash) fields to format 2 stage steps.
They appear in `view`, never in saves or route traces, so check them through `view`. Keep Python
`player.py`, `player.gd` and `validate_story.gd` in step. A change with no transition plays a 0.2 s
dissolve, so probes that compare mid-screen state call `_process` to settle it. Native UI probes
with many awaits need `native_ui_probe(..., frames=...)`, or the engine quits first. Prompt v7 also
adds a missing `generate_voice` when a new line is marked for voice. Read
`docs/reports/2026-11-07-transitions.md`.

[ADR 0066](docs/adr/0066-music-ambience-and-sound-effects.md) (runtime 0.10.0, prompt v8, migration
0050) adds Ogg Vorbis `music` assets and WAV sound effects, with stage fields `music`, `ambience` (null
stops; in `stage`, left out while silent) and `sound` (view only). A new asset kind must be added to
`validation.py`, `package.py`, `validate_story.gd`, `player.gd`, `bootstrap.gd`, `export_presets.cfg`,
`build_child.py`, `previewProtocol.ts`, `bridge.js`, the asset routes and `narrative_package_v2.py`. Only a
real playtest and a real release prove them all. `prompts.py` orders stage fields seen before heard, because
a grammar cannot go back for an earlier field. Read `docs/reports/2026-11-07-music-and-sound.md`.

[ADR 0068](docs/adr/0068-generation-waits-for-the-creators-press.md) (migration 0051, prompt v9)
ends **Generate automatically**: every action and child session shows a card in the chat, and nothing
runs until the person presses Generate. `ActionQuote` is written by the server, and its `parts` must be
what admission charges (`test_every_card_costs_exactly_what_it_says`), so a new action needs a quote and
a row in that test. `act_for` gives the worker's session the deployment's prices. Read
`docs/reports/2026-11-07-generation-cards.md`.

[ADR 0069](docs/adr/0069-saying-when-the-gpu-is-asleep.md) (migration 0052) tells people when the GPU is
down, in chat and wherever they generate. GPU workers keep a row fresh with `gpu_heartbeat`, and `record_gpu_state`
is what the controller (#197) will call. A new GPU worker needs the heartbeat and a line in `expected_kinds`.
`FLINT_GRAPH_NARRATIVE_GPU_SLEEPS` is only true with a controller, or the message correctly says it won't wake.
Read `docs/reports/2026-11-07-gpu-wake-message.md`.

[ADR 0067](docs/adr/0067-generated-music.md) (migration 0053, prompt v10) adds opt-in generated music through
`narrative_music_worker` and the isolated `runtimes/musicgen` (ACE-Step 3.5B). `music` is a usage kind, so a new
kind of generation must update `usage_charges`, `KINDS`, `_NOUNS` and `usageModel.ts`, or a real key gets a 500; test
paid paths in invite mode. Nobody has listened to the output yet. Read `docs/runbooks/narrative-music-generation.md` and
`docs/reports/2026-11-07-generated-music.md`.

[ADR 0070](docs/adr/0070-a-gpu-that-sleeps.md) (migration 0054, #196-#198) lets the GPU sleep: `narrative_gpu_dispatch`
relays every GPU topic from the always-on tier, `NARRATIVE_GPU_EXECUTE_ONLY` stops workers relaying, and
`narrative_gpu_controller` starts and stops one tagged EC2 instance (pure `decide`, port `GpuInstance`). A new GPU kind
needs a step in `narrative_gpu_dispatch.py`, a dispatcher in `build_dispatchers`, and a table in `gpu_work`. The laptop keeps
combined mode. Never exercised on real AWS; read `docs/runbooks/gpu-sleep-and-wake.md` and
`docs/reports/2026-11-07-gpu-that-sleeps.md`.

[ADR 0071](docs/adr/0071-title-screen.md) (runtime 0.11.0, prompt v11) adds an optional title screen: `theme.title` with
`background` and `music`, drawn by `vn_view.gd`, never in saves or route traces. With neither set a game opens on its first
line as before, so native probes are unaffected. The assistant uses its own exact `set_title_screen`, because given the whole
theme the live model invented every colour. Read `docs/reports/2026-11-07-title-screen.md`.

[ADR 0072](docs/adr/0072-naming-the-player.md) (runtime 0.12.0, prompt v12) lets players name the protagonist: format 2
`player` and a `name` node, `{name}` in text, and `player_name` in state, saves and traces only when declared. `clean_name` must
stay identical in `values.py` and `player.gd`. Keep Python, `player.gd` and `validate_story.gd` in step. Read
`docs/reports/2026-11-07-player-name.md`.

Prompt v13 and `turn.py` make a first request usable: a request to write gets writing, not questions about clothes; a promise
with no proposal is sent back; a first story replaces the blank starter (only while it holds the starter's exact words); edits
that change nothing are dropped, so a pictures request shows only its cards. The end-to-end creator run stopped at the sprites.
Read `docs/reports/2026-11-07-first-creator-run.md`.

[ADR 0073](docs/adr/0073-project-trash-and-permanent-delete.md) (migration 0055) adds the project trash (`archived_at`), Delete forever,
rename and a first-time guide. A purge removes files, then rows; `project_tables()` and `project_loops()` read the schema, so a new table
holding a project's rows needs only a `project_id`. Immutable tables allow one thing: a `DELETE` of a row whose own project has
`purge_started_at` set. A new kind of job must join `RUNNING_WORK`. Read `docs/reports/2026-11-07-project-trash-and-guide.md`.

[ADR 0075](docs/adr/0075-credits-for-a-short-visit.md) (migrations 0056-0057) sets credits for a 15-minute visit: new invitations grant 100, and a
release build costs 5 because it uses no GPU. A test holds a typical visit to that default, so check it when changing prices. Open-mode users and
operators are unlimited: `own_server` and `credits_used` in the access status, `ownServer` beside `metered` in the frontend, and usage marked
`own_server` that never counts against an allowance and never gives access. The Assets page groups a job's options with `assetSets`.

[ADR 0076](docs/adr/0076-screenshots-for-the-assistant.md) (migration 0058, prompt v14) lets people paste a screenshot to the assistant. Its writing model
cannot see, so opt-in `FLINT_GRAPH_NARRATIVE_ASSISTANT_VISION_MODEL` (`lfm3-vl:2b`) describes each picture in words first. Pictures are private, never in a
story or game, and go with the project. Rewriting a stage step keeps who is on it unless the request is to take them off. Read
`docs/reports/2026-11-07-assistant-images.md`.

[ADR 0077](docs/adr/0077-one-small-server-and-one-sleeping-gpu.md) prepares the AWS deployment: k3s on a `t3a.medium` and a sleeping `g6.xlarge`, with CDK in
`deploy/cdk`, Ansible in `deploy/ansible`, Flux in `deploy/flux`, manifests in `deploy/k8s` and the estimate in `deploy/cost`. Nothing has been created in AWS, and
creating it spends money, so never run `cdk bootstrap` or `cdk deploy` without being asked each time. `FLINT_GRAPH_*` lists are JSON in `config.env`; `tests/unit/test_deploy_manifests.py`
runs them through `Settings`. A new GPU worker needs a Deployment like those in `gpu-workers.yaml`. Playtests, release builds and a sign-in provider are not deployed yet. Read
`docs/runbooks/aws-deployment.md` and `docs/reports/2026-11-07-aws-preparation.md`.

## Project Snapshot

#134 now has the Langfuse authoring/reviewed-lock decision contract in ADR 0044,
`docs/architecture/prompt-catalog-inventory.md` and the ADR 0029 prompt-management
threat addendum. `docs/reports/2026-11-01-langfuse-prompt-contract.md` records the
compatibility qualification: server 4.72.0 / isolated SDK 4.15.0 with existing
OTel 1.43.0. That contract-only delivery enabled no runtime. The catalog, optional
profile and resolver (#135–#137), including assistant/image/scene-art defaults, are
now implemented and qualified in `docs/reports/2026-11-01-langfuse-prompt-migration.md`.
The shipped policy lists are unchanged. Further quality/context work remains
separate (#138–#140); keep #79 trace export separate from prompt management.

The user added #133–#167 on 2026-10-30: M35 prompt management, M36 context
engineering, M37 controlled memory, M38 package-v2 visual novel presentation,
plus shared conversations and narrative assistant/art work. Read the updated
`docs/product/narrative-game-backlog.md` dependency map. #124's bounded v1
release work is delivered; #134/#135 precede #126, while #140 follows #126. Package v2
requires #124/#128/#157 and preserves existing v1 releases/saves. Planned issues
are not delivered functionality; the final #132 game should exercise M38 parity.

FlintGraph is an AI-assisted visual-novel Studio. Its shared platform services include the ingestion control plane, a Temporal-backed content pipeline, provenance-rich staged extraction proposals, a resolved knowledge graph with reviewable reversible merges, rebuildable retrieval indexes, LangGraph-backed query orchestration with streamed, faithfulness-checked, citation-bearing answers and provenance APIs, real-model defaults outside tests, an offline evaluation quality gate, document lifecycle cleanup, OIDC workspace access, and controlled-deployment public API hardening. These services support document and context workflows; Studio feature status is recorded above and in the narrative delivery reports.

Implemented document-context path:

```text
API intake -> immutable raw object in MinIO
    -> durable ingestion job + outbox message
    -> outbox relay -> Temporal ingestion workflow
    -> worker: verify hash -> parse -> chunk -> extract staged proposals
    -> verify exact evidence spans + persist extraction run/invocation/staged records
    -> proposal candidates
    -> per-tenant staged resolution (auto attach / review / new entity)
    -> aggregate relationships
    -> project resolved graph into Neo4j
    -> index chunks into PostgreSQL embeddings + Neo4j vectors + OpenSearch lexical records
    -> primitive lexical/vector/neighborhood retrieval APIs
    -> LangGraph query run -> classify/link/retrieve/fuse/rerank/pack
    -> draft answer -> repair citations -> support check -> abstain/finalize
    -> persisted SSE events + inspectable query run + answer provenance
    -> offline golden-dataset eval gate + optional secrets-gated live eval
    -> OIDC-authenticated workspace users with role-scoped MVP setup and app flows
    -> explicit CORS/trusted-host/TLS/request-limit/SSRF/rate-limit deployment boundary
```

PostgreSQL is the system of record for the control plane, identity, workspace membership, extraction provenance, staged proposals, resolved graph, retrieval index versions, embeddings, coverage, backfill state, query runs, query events, candidates, context packs, answer metadata, answer claims, support decisions, and answer provenance. Neo4j and OpenSearch are idempotent, rebuildable projections. MinIO stores immutable raw and derived artifacts. Evaluation datasets, recorded evaluations, reports, and baselines are file-based under `evals/`. The API serves workspace, document/job, graph, review, audit, setup/readiness, index inspection, backfill, lexical search, vector search, graph-neighborhood, query-run, query-event, SSE query streaming, answer-provenance, and citation-provenance endpoints; dedicated extraction inspection endpoints are deferred.

Earlier milestones (durable dispatch, content pipeline) remain in place; see `docs/milestones/`.

## Ground Rules

- Document durable decisions and completed milestone behavior under `docs/`.
- Use `notes/` for scratch planning, manual test notes, and working handoff context. `notes/` is gitignored.
- Add or update tests before changing implementation behavior.
- Prefer focused changes that preserve the current modular shape.
- Do not treat `X-Tenant-ID` alone as authentication. In OIDC mode it is a workspace selector that must be authorized through server-side membership.
- Do not revert unrelated user changes in the working tree.

## Useful Commands

```powershell
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run mypy
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run alembic upgrade head --sql
docker compose config
docker compose up --build
docker compose down -v
```

Convenience make targets exist for Unix-like shells:

```bash
make test
make lint
make typecheck
make eval-gate
make check
make relay
make worker
```

On Windows PowerShell, running the `uv` and `docker compose` commands directly is usually clearer than relying on `make`.

## Local Services

Docker Compose exposes:

- API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- Temporal Web UI: `http://localhost:8233`
- Grafana: `http://localhost:3000`
- Neo4j browser: `http://localhost:7474` (user `neo4j`, password `flintgraphpassword`)
- PostgreSQL host port: `localhost:55432`
- Temporal gRPC host port: `localhost:7233`
- Neo4j Bolt host port: `localhost:7687`
- OpenSearch: `http://localhost:9200`

The `temporal` compose service uses `temporalio/temporal:latest` with `server start-dev --ip 0.0.0.0 --namespace default`. Temporal's development server includes a Web UI by default.

## Key Files

- `src/flint_graph/api/routes/documents.py`: document, ingestion job, cancellation, and job event endpoints.
- `src/flint_graph/application/services/ingestion_jobs.py`: transactional document-version/job/event/outbox creation.
- `src/flint_graph/application/services/job_transitions.py`: explicit job state transition rules.
- `src/flint_graph/application/services/job_cancellation.py`: API-side cancellation and cancellation outbox creation.
- `src/flint_graph/application/services/outbox.py`: outbox append helper and trace-context capture.
- `src/flint_graph/application/services/outbox_relay.py`: pending outbox polling and Temporal dispatch.
- `src/flint_graph/infrastructure/temporal.py`: Temporal client adapter.
- `src/flint_graph/workflows/ingestion.py`: `IngestDocumentWorkflow`.
- `src/flint_graph/worker/activities/ingestion.py`: worker activities that mutate job state.
- `src/flint_graph/processes/outbox_relay.py`: long-running relay process.
- `src/flint_graph/processes/ingestion_worker.py`: long-running Temporal worker.
- `src/flint_graph/infrastructure/db/models.py`: SQLAlchemy models.
- `migrations/versions/0002_outbox_messages.py`: outbox migration.
- `docs/runbooks/durable-ingestion-dispatch.md`: durable dispatch runbook.
- `docs/architecture/object-storage-contract.md`: future object-storage contract.
- `docs/adr/0003-transactional-outbox-and-temporal.md`: durable dispatch ADR.

Milestone 04 knowledge graph:

- `src/flint_graph/application/entity_resolution/`: pure normalization and scoring.
- `src/flint_graph/application/services/candidate_generation.py`: pg_trgm blocking.
- `src/flint_graph/application/services/resolution.py`: banded resolution + advisory lock + relationship aggregation.
- `src/flint_graph/application/services/entity_merge.py`: soft merge with undo log + unmerge.
- `src/flint_graph/application/services/review.py`: review-queue decisions.
- `src/flint_graph/application/services/graph_projection.py`: Neo4j projection/reconcile.
- `src/flint_graph/workflows/resolution.py` and `src/flint_graph/worker/activities/resolution.py`: per-tenant resolution workflow/activities.
- `src/flint_graph/api/routes/graph.py`: entity, review, merge/unmerge, and audit endpoints.
- `src/flint_graph/infrastructure/neo4j.py` and `neo4j_migrations.py`: Neo4j client and Cypher migration runner.
- `migrations/versions/0005_knowledge_graph.py` and `migrations/neo4j/`: graph schema.
- `docs/milestones/04-knowledge-graph.md`, `docs/adr/0004-postgres-authoritative-resolution-neo4j-projection.md`, `docs/architecture/knowledge-graph-contract.md`, `docs/runbooks/knowledge-graph-*.md`.
Milestone 05 provenance-rich extraction:

- `src/flint_graph/application/extraction_proposals.py`: provider-neutral proposal models and deterministic provider.
- `src/flint_graph/application/extraction_evidence.py`: exact quote evidence resolver.
- `src/flint_graph/application/services/provenance_extraction.py`: transactional extraction run, invocation, evidence, staged-record, and manifest persistence.
- `src/flint_graph/application/services/proposal_candidate_generation.py`: non-destructive proposal candidate generation.
- `src/flint_graph/application/services/staged_resolution.py`: canonical resolution over staged proposals.
- `src/flint_graph/infrastructure/ollama.py`: Ollama proposal adapter at the infrastructure edge.
- `migrations/versions/0006_provenance_extraction.py` and `0007_staged_resolution_state.py`: provenance and staged-resolution schema.
- `docs/milestones/05-provenance-rich-extraction.md`, `docs/adr/0005-staged-extraction-proposals-before-canonical-resolution.md`, `docs/architecture/extraction-proposal-contract.md`, `docs/runbooks/provenance-extraction-*.md`.

Milestone 06 retrieval indexes:

- `src/flint_graph/application/embeddings.py`: provider-neutral embedding contract and deterministic model.
- `src/flint_graph/infrastructure/embedding_factory.py`: shared embedding model construction.
- `src/flint_graph/infrastructure/embeddings.py`, `ollama.py`: embedding adapters.
- `src/flint_graph/application/services/retrieval_index_versions.py`: index-version transitions.
- `src/flint_graph/application/services/indexing.py`: document-version indexing, coverage, and projection replay.
- `src/flint_graph/application/services/index_backfill.py`: backfill job state and eligibility.
- `src/flint_graph/application/services/retrieval.py`: primitive retrieval API service layer.
- `src/flint_graph/application/services/lexical_projection.py` and `vector_projection.py`: projection record/query builders.
- `src/flint_graph/api/routes/retrieval.py`: index, backfill, lexical/vector search, and neighborhood endpoints.
- `src/flint_graph/workflows/indexing.py`, `backfill.py`: retrieval indexing and backfill workflows.
- `src/flint_graph/worker/activities/indexing.py`, `index_backfill.py`: worker activities.
- `src/flint_graph/processes/retrieval_index_reconcile.py`: projection reconcile command.
- `migrations/versions/0008_retrieval_index_ledger.py`, `0009_document_index_coverage.py`, and `migrations/neo4j/0002_chunk_vector_indexes.cypher`: retrieval schema.
- `docs/milestones/06-retrieval-indexes.md`, `docs/adr/0006-rebuildable-retrieval-indexes.md`, `docs/architecture/retrieval-index-contract.md`, `docs/runbooks/retrieval-index-*.md`.

Milestone 07 query orchestration:

- `src/flint_graph/application/query_orchestration.py`: provider-neutral query contracts and deterministic providers.
- `src/flint_graph/application/services/query_runs.py`: query-run ledger and event persistence.
- `src/flint_graph/application/services/query_planning.py`: deterministic classification and entity linking.
- `src/flint_graph/application/services/query_orchestration.py`: LangGraph query runtime.
- `src/flint_graph/application/services/query_fusion.py`: candidate fusion and reranking persistence.
- `src/flint_graph/application/services/query_context_packing.py`: citation-ready context packs.
- `src/flint_graph/application/services/query_answering.py`: answer events, citations, and completion.
- `src/flint_graph/api/routes/query.py`: query-run, event replay, and SSE streaming endpoints.
- `migrations/versions/0010_query_run_ledger.py`: query-run schema.
- `tests/fixtures/query_orchestration_eval_cases.json`: deterministic query eval fixtures.
- `docs/milestones/07-query-orchestration.md`, `docs/adr/0007-langgraph-query-orchestration.md`, `docs/architecture/query-orchestration-contract.md`, `docs/runbooks/query-orchestration-*.md`.

Milestone 08 grounded answer generation:

- `src/flint_graph/application/query_faithfulness.py`: citation repair, deterministic support checking, and abstention policy helpers.
- `src/flint_graph/application/services/query_faithfulness.py`: draft-to-verified-answer runtime pipeline.
- `src/flint_graph/application/services/query_answering.py`: verified answer event emission, answer-claim persistence, and completion.
- `src/flint_graph/application/services/query_provenance.py`: tenant-scoped answer and citation provenance readers.
- `src/flint_graph/infrastructure/ollama.py`: Ollama answer generation and streaming adapter.
- `src/flint_graph/infrastructure/answer_generator_factory.py`: answer generator and support checker provider selection.
- `src/flint_graph/api/routes/query.py`: query-run, event replay, SSE streaming, provenance, and citation endpoints.
- `migrations/versions/0011_answer_faithfulness.py`: query-run faithfulness columns and `query_answer_claims`.
- `tests/fixtures/query_orchestration_eval_cases.json`: deterministic query and faithfulness eval fixtures.
- `docs/milestones/08-grounded-answer-generation.md`, `docs/adr/0008-grounded-answer-generation-and-faithfulness.md`, `docs/architecture/answer-faithfulness-contract.md`, `docs/runbooks/grounded-answer-generation-*.md`.

Milestone 09 real models and evaluation:

- `src/flint_graph/infrastructure/anthropic.py`: Anthropic answer generation, streaming, and support checking adapters.
- `src/flint_graph/config.py`: env-aware provider defaults and credential validation.
- `src/flint_graph/evaluation/`: dataset loading, metrics, experiment runner, reports, baselines, recorded evaluators, and comparisons.
- `src/flint_graph/cli/eval.py`: `flint-graph-eval` CLI for offline scoring, comparisons, and baseline updates.
- `evals/datasets/acme-smoke/`: fixed golden corpus and labeled queries.
- `evals/experiments/acme-smoke.yaml`: offline/live experiment thresholds.
- `evals/reports/acme-smoke/`: deterministic recorded eval fixture and accepted baselines.
- `.github/workflows/ci.yml`: offline deterministic PR quality gate.
- `.github/workflows/live-eval.yml`: scheduled/manual secrets-gated live eval gate.
- `docs/milestones/09-real-models-and-evaluation.md`, `docs/adr/0009-default-real-models-offline-safe.md`, `docs/adr/0010-evaluation-platform-and-quality-gates.md`, `docs/architecture/evaluation-contract.md`, `docs/runbooks/real-models-developer.md`, `docs/runbooks/evaluation-*.md`.

Milestone 10 local-first usable RAG:

- `src/flint_graph/application/services/search_readiness.py`: tenant-scoped active-index search readiness summary.
- `src/flint_graph/infrastructure/ollama.py`: Ollama answer, embedding, extraction, and support-checking adapters.
- `src/flint_graph/application/services/query_runs.py`: persisted compact query diagnostics in query-run metadata.
- `src/flint_graph/api/routes/retrieval.py`: `/v1/search-readiness`.
- `src/flint_graph/api/routes/query.py`: query creation guard for searchable content.
- `frontend/src/pages/AskPage.tsx`: readiness-gated Ask flow and diagnostics panel.
- `frontend/src/pages/UploadPage.tsx`: backend readiness document status view.
- `docs/milestones/10-local-first-usable-rag.md`, `docs/adr/0011-local-first-ollama-readiness-diagnostics.md`, `docs/runbooks/local-ollama-rag.md`, `docs/runbooks/frontend-e2e-qa-guide.md`.

Milestone 12 MVP bootstrap and access boundary:

- `src/flint_graph/infrastructure/oidc.py`: Keycloak-compatible OIDC token verifier.
- `src/flint_graph/application/services/authz.py`: authenticated principal, user upsert, and workspace role checks.
- `src/flint_graph/application/services/workspaces.py`: workspace and membership service layer.
- `src/flint_graph/application/services/retrieval_bootstrap.py`: idempotent active retrieval-index bootstrap from settings.
- `src/flint_graph/api/dependencies.py`: current-user dependency and tenant viewer/member/admin authorization dependencies.
- `src/flint_graph/api/routes/workspaces.py`: workspace listing, creation, and member-management endpoints.
- `src/flint_graph/api/routes/retrieval.py`: system readiness, active-index bootstrap, active-index backfill, and backfill listing endpoints.
- `frontend/src/lib/auth.tsx`: dev/OIDC frontend auth provider.
- `frontend/src/lib/workspace.tsx`: server-backed workspace selection.
- `frontend/src/pages/SetupPage.tsx`: readiness, index bootstrap, and backfill UI.
- `migrations/versions/0014_identity_memberships.py`: users and workspace memberships.
- `docs/milestones/12-mvp-bootstrap-and-access-boundary.md`, `docs/architecture/security-boundary.md`.

## Current Invariants

- A document belongs to one tenant.
- Tenant-scoped reads return 404 for foreign resources.
- Every new ingestion attempt creates one immutable document version.
- Reusing an idempotency key in the same tenant returns the existing job.
- The initial `job.queued` event and `ingestion.job_queued` outbox message are written in the same API transaction as the job.
- Cancellation writes `job.cancelled` plus `ingestion.job_cancelled` before leaving the API transaction.
- The relay marks an outbox message `published` only after Temporal accepts the start or cancellation request.
- Job state changes go through explicit transition rules and append events.
- The relay prioritizes queued workflow-start messages before cancellation messages when both are available.
- Model output is staged and evidence-verified before it can affect canonical graph state.
- Accepted staged entities, relations, and claims retain at least one verified evidence span.
- Canonical graph mutation happens in deterministic resolution services, not provider adapters.
- Retrieval index versions are explicit and active per global or tenant scope.
- Chunk embeddings are tied to chunk hashes and retrieval index versions.
- Neo4j and OpenSearch retrieval records are rebuildable from PostgreSQL.
- Primitive retrieval APIs always apply tenant filters.
- Query APIs always apply tenant filters.
- Query runs use visible active retrieval index versions.
- Query events are persisted in monotonic per-run order.
- Every answer citation maps to a packed context record.
- Every persisted answer claim carries a support decision.
- Unsupported generated answers abstain rather than serving fabricated citations.
- Query provenance APIs apply tenant filters and resolve from PostgreSQL.
- `env=test` resolves model providers to deterministic values and remains offline.
- Non-test real provider selections validate required credentials at startup.
- Evaluation baselines are explicit reviewed files, never silently updated.
- The PR quality gate uses deterministic recorded evaluations and requires no live model service.
- Query creation requires at least one completed document-version coverage row for the selected active retrieval index.
- Search readiness is derived from PostgreSQL index coverage, not Neo4j or OpenSearch projection state.
- Query diagnostics are a compact derived summary persisted in query-run metadata; query events and provenance remain the detailed inspection source.
- OIDC mode requires a valid bearer token before tenant-scoped API access.
- `env=staging` and `env=production` reject dev auth unless explicitly overridden.
- `env=staging` and `env=production` require explicit public URL, CORS origins,
  trusted hosts, TLS, non-default object-store credentials, and enabled rate
  limiting.
- Tenant-scoped dependencies authorize `X-Tenant-ID` against active workspace membership.
- Workspace roles are ordered as viewer, member, admin, owner.
- Workspace names are unique per person, ignoring case, among the workspaces they actively belong to; they are not unique across the server (migration 0049).
- Graph review/merge mutations, document deletion/cleanup retry, and retrieval setup/backfill require admin or owner.
- Document creation/upload/intake requires member, admin, or owner.
- Server-backed workspace, document list, setup readiness, backfill list, and query history are available to the frontend.
- URL intake blocks private/local network targets outside local/test unless
  explicitly allowed.
- Oversized uploads and body-bearing requests are rejected before persistence or
  background work.

## Temporal Notes

- Workflow name: `IngestDocumentWorkflow`.
- Task queue: configured by `FLINT_GRAPH_TEMPORAL_TASK_QUEUE`, default `ingestion`.
- Workflow ID: `ingestion-job-{job_id}`.
- Workflow memo stores `trace_context` from outbox headers.
- Workflow start uses duplicate-safe Temporal policies so retrying the relay does not create duplicate workflows.
- Cancellation dispatch uses the same workflow ID and calls Temporal workflow cancellation.
- Indexing workflow name: `IndexDocumentVersionWorkflow`.
- Backfill workflow name: `IndexBackfillWorkflow`.
- Indexing workflow ID: `index-document-version-{document_version_id}-{retrieval_index_version_id}`.
- Backfill workflow ID: `index-backfill-{job_id}`.

## Known Limitations

- Small local extraction models can produce sparse or noisy proposals; the pipeline validates evidence and persists accepted output faithfully.
- Dedicated extraction inspection APIs are not implemented yet; use PostgreSQL queries in the provenance extraction runbook.
- `unmerge` reverses the most recent merge and assumes no conflicting interleaved graph changes.
- Neo4j projection re-reconciles the whole tenant subgraph after each resolution rather than applying deltas.
- Trace context is captured and carried into Temporal memo, but automatic distributed span continuation inside workflows and activities is not complete.
- The local Temporal dev server is not production Temporal.
- The compose Temporal service currently uses the `latest` image tag, which is convenient for early local development but should be pinned before production-like environments.
- OpenSearch near-real-time indexing may require refresh or polling before a just-indexed chunk appears in search.
- Query API SSE execution is request-bound; it is not a durable background workflow.
- Deterministic query and support providers are useful for repeatable smoke tests, not production answer quality.
- Small local answer models can emit malformed or sparse draft claims; citation repair and support checking bound what reaches the persisted final answer.
- Non-test defaults select Anthropic for answer/support, so no-cost local development should explicitly set deterministic or Ollama query providers when no Anthropic key is available.
- The live eval workflow checks a live-captured recording file; capture automation is intentionally separate from the offline PR gate.
- Switching the local embedding provider/model/dimension requires a compatible retrieval index version and backfill before documents become searchable.
- Workspace creation is currently open to any authenticated user; invitation or system-admin bootstrap policy is deferred.
- OIDC group-to-workspace synchronization and SCIM lifecycle management are not implemented.
- The frontend stores the selected workspace ID and locally tracked transient upload jobs in `localStorage`; backend readiness and document/query lists are durable.

## Before Ending A Change

Run the narrowest meaningful verification, and prefer the full set when behavior changed:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run alembic upgrade head --sql
docker compose config
```

Tell the user exactly which commands passed and which were skipped.

Private project style training is now available as an opt-in slice of #184:
[ADR 0050](docs/adr/0050-private-project-style-adapters.md), migration 0037,
`runtimes/stylegen`, and a dedicated `narrative_style_worker`/queue. Look → Project
art style explicitly selects 4–12 approved images and reviewed captions with
training-rights confirmation; Characters → Poses chooses a completed private
version/strength. Rank-4 LoRAs target the exact klein pose base pin, never SDXL CG
or expression workers. Weights stay outside assets/exports and have no public
download route. Optional isolated MLflow 3.17.2 mirrors numeric losses/resources
and hashes through bounded REST calls, with no inputs/artifacts/autologging and
no root OTel dependency changes. A real four-image 200-step run and adapter-backed
pose completed on the 12 GB GPU; this is not a style/lighting guarantee or creator
calibration. Character-specific training remains follow-up. Read
`docs/reports/2026-11-02-private-style-adapters.md` and the image runbook before
rollout. Keep the active Studio/playtest running; apply additive schema while idle
and leave any existing process reload to its owner.

[ADR 0051](docs/adr/0051-reviewed-character-look-adapters.md), migration 0038,
extends private training with a reviewed character/look target. Characters →
Poses → Character look training requires 4–12 same-look images including the
approved base, edited content captions, same-look/anatomy review and training
rights. The immutable sidecar/dataset look hash is checked at admission and on
training/render retries. Pose selection offers only this exact character look's
versions plus project styles; existing style requests/replay hashes stay valid.
The worker/klein recipe/private weights are reused, while MLflow separates runs
by an allowlisted kind. No automatic anatomy score or quality guarantee is implied:
a user identified an extra boot in the earlier QA seated pose despite correct
identity/clothes; that image is excluded from the character training dataset,
and replacement candidates remain subject to review. See
`docs/reports/2026-11-02-character-look-adapters.md`. Preserve the existing Studio
and the Aster QA on 5276 while they are in use; this delivery uses another
isolated fixture on 8278/5278/5298. Do not close all of #184 or M40 from this slice.


[ADR 0052](docs/adr/0052-character-and-style-pose-adapters.md), migration 0039,
adds an explicit character adapter beside the existing pose style selection.
`NARRATIVE_POSE_MAX_ADAPTERS=2` enables separate Studio controls and protocol 4;
the default/older API keeps one chooser and protocols 1–3. Both frozen versions
must be completed for this exact base pin, and the character version must match
the exact reviewed look/approved base. Strengths are 0.1–1 with a combined total
at most 1. Worker/parent/child verify private bytes and record both hashes/roles;
weights never enter assets, games or tracking artifacts. See
`docs/reports/2026-11-02-combined-pose-adapters.md` for real qualification and
limits. Preserve main Studio, Aster QA on 5276 and character QA on 5278; this
qualification uses a new random database/queues and 8280/5280/5300. Candidate
anatomy/style/lighting review remains manual.


[ADR 0053](docs/adr/0053-manual-anatomy-review-and-training.md), migration 0040,
adds manual anatomy verdicts shared by image SHA-256 within a workspace/project,
with a separate optimistic version. Legacy feedback writes preserve anatomy;
new writes require the current anatomy version. Compare look and asset cards
show the verdict independently of identity/clothes, and known flawed sources
are excluded from both character and project-style training. The API checks
admission; the style worker checks input loading, progress and publication under
the review project lock. Image approval and existing completed adapters remain
available. This adds no automatic detector, calibration, model/recipe change or
Godot bump. Read `docs/reports/2026-11-02-anatomy-training-review.md` for real
Temporal, browser, PostgreSQL and deployment qualification. Use synthetic fixtures;
do not infer anatomy verdicts from old notes or annotate creator projects.


[ADR 0055](docs/adr/0055-skeletal-guidance-for-seated-poses.md), migration 0042,
adds opt-in **Body guide → Seated — both feet on the floor** to Poses. A pinned
Apache-2.0 RefControl 4B pose adapter supplies geometry independently of the
approved character look and optional private style/character versions. Protocol 6
renders a frozen COCO-18 skeleton first and the approved appearance reference
second. Guides replace the supplemental character view and require max references 2.
`NARRATIVE_POSE_GUIDES_ENABLED` defaults off; set its control model directory and
manifest pin and deploy API/worker together. Keep `seated-front-v1` coordinates,
0.8 adapter strength, COCO-18 renderer and appearance preprocessing immutable;
version the guide/recipe when changing them. No weights ship in games; generated
notices carry the source credit, including local repairs of guided outputs.
The reported missing leg reproduces before cutout, and is a negative regression
fixture, never a training positive. A guide is not an anatomy/appearance guarantee;
review hands, limbs and costume details. See
`docs/reports/2026-11-02-seated-pose-guidance.md` for exact evidence and commands.

Body guidance also offers `standing-front-v1` and `walking-three-quarter-v1`
under ADR 0055, using the same pinned model, protocol 6 and fixed 0.8 recipe.
Capabilities carry editable pose suggestions outside frozen guide data. Keep all
released guide coordinates immutable, including the original seated hash. Deploy
API and pose child together; older children reject the new IDs. There is no new
migration, prompt or game runtime pin. Read
`docs/reports/2026-11-02-standing-and-walking-guides.md` for real output review and
verification. Properly composite RGBA images before judging cutout edges: hidden
RGB bleed at alpha zero can look striped in raw image-tool previews.

[ADR 0056](docs/adr/0056-reviewed-training-caption-suggestions.md) adds optional
per-image training-caption proposals from the existing pinned CPU look tagger.
Project members can read tags for an approved bounded PNG; raw observations keep
source/model hashes. Release the authentication/read transaction before tagging,
then lock/recheck the project and source before writes. Suggestions exclude
rating/gender/count/name/style instructions, stay separate from edited text, and
apply only explicitly, resetting training confirmations. Manual entry survives
unavailable taggers. No migration, recipe, prompt/policy or game runtime change;
this is training-input assistance, not calibrated scoring or a quality guarantee.
Read `docs/reports/2026-11-02-training-caption-suggestions.md`. Broader #184/M40
acceptance remains open beyond this slice.

[ADR 0057](docs/adr/0057-reference-conditioned-character-training.md) adds optional
approved-image conditioning to private character LoRA training. The default-off
`NARRATIVE_STYLE_REFERENCE_TRAINING_ENABLED` admits explicit `conditioning:
"reference"` only with a reviewed character/look target. Deploy API, style worker
and stylegen together. Recipe/protocol 2 finds the frozen base by hash, caches a
white-composited reference within 512 pixels, appends clean reference tokens with
separate position IDs and computes loss only on target tokens. Parent checks the
reference/helper provenance before publication. Legacy recipe/protocol 1,
idempotency and weights stay valid; no migration, prompt/policy/model or Godot
change. Character training exposes the option and records its mode. See
`docs/reports/2026-11-04-reference-conditioned-training.md`; broader #184 and
creator-calibrated anatomy/style/identity evaluation remain open.

<!-- BEGIN AWS Agent Toolkit rules -->
AWS CLI profile for this work: `flintgraph`. Selected Region: `ap-southeast-2`.

# AWS Guidance for the new AWS experience

This user has signed up for the new AWS experience. This experience lets you sign into AWS using a social provider and requires the following additional context.

Where this guidance conflicts with the project's own instructions, the project's instructions take precedence.

## Context

### Terminology:

- Say "project" instead of "account" — a project contains an AWS account and settings for sharing with other collaborators
- Say "team member" instead of "IAM user" — users are invited by email, not created or federated in IAM
- Say "AWS Settings" when referring to management tasks at [settings.aws.com](https://settings.aws.com/) (project management, billing, team members, spend limits). Users view their actual AWS resources in the AWS Management Console.
- Say "selected Region" when referring to the user's Region — not "home Region"
- The user has a managed IAM experience. This includes a managed service control policies (SCP) and resource control policies (RCP) that govern the use of AWS. They will still need to use IAM to create policies to let services work with each other. If there are questions about the SCPs or RCPs, go to the documentation at https://docs.aws.amazon.com/accounts/latest/reference/scps-and-rcps-for-projects.html

### Constraints:

- All projects share a single AWS Region determined by the user's contact address. Resources cannot be created in other Regions
- When developing:
  - MUST create all Regional resources in the project's assigned Region
  - You CAN create AWS WAF and Cloudwatch Logs resources in us-east-1 when there are global resources (like a global WAF instance) that require a connection to dependencies in us-east-1. You should not use these for any other reason, because resources in the selected Region will provide lower cost (due to no cross-Region traffic), increased availability (due to no cross-Region traffic), and easier manageability (due to not needing to look in another Region). When you need to do an inventory of resources, you need to look in both the selected Region and us-east-1 for Cloudwatch Logs or WAF resources.
  - MUST NOT attempt to create Lambda, API Gateway, or other Regional resources in any other Region
  - MUST direct users to confirm their Region in AWS Settings > View all projects > Overview > Additional Info > Region. If the user cannot confirm their Region, check in ~/.aws/config
  - MUST NOT use Lambda@Edge — excluded from both Lambda and CloudFront
  - MUST NOT use CloudFormation StackSets — no multi-account or multi-Region deployments
  - MUST NOT attempt cross-Region actions — no cross-Region replication for DynamoDB/S3/RDS, no multi-Region KMS keys
  - MUST NOT use Route 53 cross-Region routing — geolocation, latency-based, and failover routing policies are not available
  - CloudFront is a global service and its actions ARE allowed in `us-east-1`. A user can create a CloudFront distribution pointing to their project-region Lambda function URL or API Gateway. However, Lambda and API Gateway themselves MUST NOT be created in `us-east-1` — they must be in the project Region.
  - Reduced availability in `eu-north-1` specifically: Amazon Rekognition, Amazon Textract, Amazon Personalize, AWS App Runner are not available in that Region.
- IAM permissions for human access are managed by AWS. Don't assign roles to team members unless absolutely necessary
- The user may have a spend limit if they are on the paid plan. The limit that pauses their project if it's exceeded. If resources suddenly become inaccessible, ask if they have a spend limit configured. Only project owners can modify a spend limit.
- When developing:
  - MUST ask about spend limit status if the user reports sudden "Access Denied" errors on operations that previously worked
  - MUST direct users to check spend status in AWS Settings > Billing
  - MUST check if a user has upgraded their account to the paid plan
  - MUST ask the user if they want to clean up the successfully created resources or keep them to reduce cost
- The user sets up billing, creates spend limits, and retrieves and pays invoices in AWS Settings. The user creates budgets and optimizes their costs in the AWS Billing and Cost Management console
- Not all AWS services are available. If a service isn't working, do the following:
  1. Run the command `aws freetier get-account-plan-state`
  2. If accountPlanType": "FREE", check the [Free Tier supported services list](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html#supported-services-free-tier) next,
  3. If accountPlanType": "PAID", check the [Paid Tier supported services list](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html#supported-services-paid-plan).
  4. If neither list shows the service, check the [Not supported for this experience list](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html#unsupported-services). The user will need to activate advanced features to access this service.
- Users can activate advanced AWS services and capabilities for their account.
- For any AWS task or question — building, configuring, migrating, debugging, or operating a service, writing SDK code, authoring CDK/CloudFormation, or answering how a service works — first call `aws___search_documentation` with topic `agent_skills` and load the matching skill with `aws___retrieve_skill`. Do this even when you believe you know the answer: skills carry current service behavior that your training may not. Prefer the skill's guidance over general knowledge. Skip it only for work that does not involve AWS.

### Help level

- help_level (required): LOW, MEDIUM, or HIGH. While a user is building, you MUST ask the user: "How much guidance would you like from me? Low (I only flag security risks), medium (I ask a couple of clarifying questions if something seems off), or high (I explain what I'm doing, suggest alternatives, and flag best practices)."

You CAN update this rule file to save a user's help_level.

Constraints for each level:

**LOW:**

- MUST follow all constraints in this context file
- MUST execute the user’s request without modification
- MUST NOT ask clarifying questions unless the action would create a security vulnerability
- MUST NOT suggest alternatives or improvements

**MEDIUM:**

- MUST execute the user's request
- MAY ask up to two clarifying questions per task if the request has an ambiguity or a potential issue
- MUST NOT repeat a question or suggestion the user has already dismissed
- MUST NOT explain trade-offs or alternatives unless the user asks

**HIGH:**

- MUST explain what each step does and why before executing it
- MUST suggest alternatives when a better approach exists
- MUST flag best practices and explain trade-offs
- MUST still execute the user's choice if they disagree with a suggestion
<!-- END AWS Agent Toolkit rules -->
