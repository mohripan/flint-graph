import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/narrative/releaseModel.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const model = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

test("lost acknowledgements keep the same intent; a different revision/failed attempt gets a new key", () => {
  let keys = 0;
  const key = () => `request-${++keys}`;
  const build = model.prepareRelease(null, "revision-a", key);
  assert.strictEqual(model.prepareRelease(build, "revision-a", key), build);
  assert.deepEqual(model.prepareRelease(build, "revision-b", key), { revision_id: "revision-b", idempotency_key: "request-2" });
  const retry = model.prepareReleaseRetry(null, "job-a", key);
  assert.strictEqual(model.prepareReleaseRetry(retry, "job-a", key), retry);
  assert.deepEqual(model.prepareReleaseRetry(retry, "job-b", key), { job_id: "job-b", idempotency_key: "request-4" });
});

test("refresh updates existing releases without hiding already loaded older pages", () => {
  const current = [{ id: "new", job: { status: "running" } }, { id: "old", job: { status: "completed" } }];
  const refreshed = model.mergeReleases(current, [{ id: "new", job: { status: "completed" } }]);
  assert.deepEqual(refreshed.map(row => row.id), ["new", "old"]);
  assert.equal(refreshed[0].job.status, "completed");
  const older = model.mergeReleases(refreshed, [{ id: "old", job: { status: "completed" } },
    { id: "oldest", job: { status: "cancelled" } }], true);
  assert.deepEqual(older.map(row => row.id), ["new", "old", "oldest"]);
});

test("a requested cancellation stays active until server terminal state arrives", () => {
  const job = { status: "running", cancel_requested: true };
  assert.equal(model.releaseStatus(job), "Cancelling");
  assert.equal(model.activeRelease(job), true);
  assert.equal(model.releaseStatus({ ...job, status: "cancelled" }), "Cancelled");
  assert.equal(model.activeRelease({ ...job, status: "cancelled" }), false);
});

const revision = (id, number, extra = {}) => ({ id, revision_number: number, conflicted: false, ...extra });

test("build targets name saved revisions explicitly, including conflict copies and an unlisted draft base", () => {
  const rows = [revision("r7", 7), revision("r6", 6, { conflicted: true }), revision("r5", 5)];
  assert.deepEqual(model.buildTargets(revision("r9", 9), rows, "r9").map(row => [row.id, row.label]), [
    ["r9", "Revision 9 · current"], ["r7", "Revision 7"], ["r6", "Revision 6 · conflict copy"], ["r5", "Revision 5"],
  ]);
  assert.deepEqual(model.buildTargets(revision("r7", 7), rows, "r7").map(row => row.id), ["r7", "r6", "r5"]);
  assert.equal(model.revisionLabel("r6", rows, null), "Revision 6");
  assert.equal(model.revisionLabel("unknown", rows, revision("r9", 9)), "Earlier saved revision");
  assert.deepEqual(model.buildTargets(null, [], null), []);
});

test("builds require write access, a saved draft and no known active build of that revision", () => {
  const base = { canWrite: true, dirty: false, saving: false, busy: false, targetId: "r7", releases: [] };
  assert.equal(model.buildBlocker(base), null);
  assert.match(model.buildBlocker({ ...base, canWrite: false }), /cannot start builds/);
  assert.match(model.buildBlocker({ ...base, dirty: true }), /Save your changes first/);
  assert.match(model.buildBlocker({ ...base, targetId: null }), /Choose a saved revision/);
  const active = { revision_id: "r7", job: { status: "running", cancel_requested: false } };
  assert.match(model.buildBlocker({ ...base, releases: [active] }), /already being built/);
  assert.equal(model.buildBlocker({ ...base, releases: [{ ...active, job: { status: "failed" } }] }), null);
  assert.equal(model.buildBlocker({ ...base, releases: [{ ...active, revision_id: "r6" }] }), null);
});

test("only an authoritative completed item offers its known artifacts, in a fixed order", () => {
  const artifacts = [{ kind: "manifest" }, { kind: "web" }, { kind: "source" }, { kind: "web" }, { kind: "unknown" }];
  assert.deepEqual(model.readyArtifacts({ job: { status: "completed" }, artifacts }).map(row => row.kind),
    ["source", "web", "manifest"]);
  assert.deepEqual(model.readyArtifacts({ job: { status: "running" }, artifacts }), []);
  assert.deepEqual(model.readyArtifacts({ job: { status: "completed" }, artifacts: [] }), []);
  assert.deepEqual(["source", "web", "manifest"].map(model.artifactLabel),
    ["Godot source", "Browser build", "Release details (JSON)"]);
  assert.deepEqual([512, 2048, 5 * 1048576].map(model.formatBytes), ["512 B", "2.0 KB", "5.0 MB"]);
});

test("a resent build key is reported as already recorded, not as a new request", () => {
  const fresh = { job: { status: "queued", attempt_number: 1 } };
  assert.equal(model.replayedRelease(fresh, false), false);
  assert.equal(model.replayedRelease(fresh, true), true);
  assert.equal(model.replayedRelease({ job: { status: "completed", attempt_number: 1 } }, false), true);
  assert.equal(model.replayedRelease({ job: { status: "queued", attempt_number: 2 } }, false), true);
  const intents = model.releaseIntents();
  assert.ok(intents.builds instanceof Map && intents.retries instanceof Map);
  assert.notStrictEqual(model.releaseIntents().builds, intents.builds);
});

test("responses from another workspace or project are never applied", () => {
  const release = { tenant_id: "workspace", project_id: "project" };
  assert.equal(model.scopedRelease(release, "workspace", "project"), true);
  assert.equal(model.scopedRelease({ ...release, tenant_id: "other" }, "workspace", "project"), false);
  assert.equal(model.scopedRelease({ ...release, project_id: "other" }, "workspace", "project"), false);
});

test("historical acceptance and late snapshots cannot undo a newer or terminal build", () => {
  const current = { id: "release", artifacts: [{ kind: "source", sha256: "verified" }],
    job: { id: "retry-job", attempt_number: 2, status: "completed", cancel_requested: false } };
  const replay = { ...current, artifacts: [], job: { id: "original-job", attempt_number: 1, status: "cancelled" } };
  assert.deepEqual(model.mergeReleases([current], [replay]), [current]);
  const late = { ...current, artifacts: [], job: { ...current.job, status: "running" } };
  assert.deepEqual(model.mergeReleases([current], [late]), [current]);
  const summary = { ...current, artifacts: [] };
  assert.deepEqual(model.mergeReleases([current], [summary]), [current]);
});
