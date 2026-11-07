import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(path) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}

const { deletionBlocked, deletionList } = await load("../src/narrative/trashModel.ts");
const { GUIDE_STEPS, guideSeen, markGuideSeen } = await load("../src/narrative/guideModel.ts");
const { api } = await load("../src/lib/api.ts");

const empty = { revisions: 0, files: 0, characters: 0, conversations: 0, releases: 0, working: [] };

test("the warning names every kind of thing that would be lost", () => {
  const lines = deletionList({ ...empty, revisions: 4, files: 24, characters: 2, conversations: 3, releases: 1 });
  assert.deepEqual(lines, [
    "The story and its 4 saved revisions",
    "24 pictures, voices and music files",
    "2 characters",
    "3 conversations with the assistant",
    "1 released game, whose downloads will stop working",
  ]);
});

test("the warning counts one of something correctly and leaves out what is not there", () => {
  assert.deepEqual(deletionList({ ...empty, revisions: 1, files: 1 }), [
    "The story and its 1 saved revision",
    "1 picture, voice or music file",
  ]);
  assert.deepEqual(deletionList(empty), []);
});

test("delete is held back only while the project is working", () => {
  assert.equal(deletionBlocked(empty), null);
  assert.match(deletionBlocked({ ...empty, working: ["1 assistant reply", "2 picture jobs"] }),
    /still working on 1 assistant reply and 2 picture jobs/);
});

test("the guide is shown until it is dismissed, and survives storage that throws", () => {
  const memory = new Map();
  const storage = { getItem: key => memory.get(key) ?? null, setItem: (key, value) => memory.set(key, value) };
  assert.equal(guideSeen(storage), false);
  markGuideSeen(storage);
  assert.equal(guideSeen(storage), true);
  const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(guideSeen(blocked), false);
  assert.doesNotThrow(() => markGuideSeen(blocked));
  assert.equal(guideSeen(null), false);
});

test("the guide walks from an empty page to a game someone can play", () => {
  const text = GUIDE_STEPS.map(step => `${step.title} ${step.text}`).join(" ");
  for (const word of ["Assistant", "Accept", "Generate", "Playtest", "Releases"]) assert.match(text, new RegExp(word));
});

test("trash calls are scoped to the workspace and go to the right places", async () => {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return init?.method === "DELETE" ? new Response(null, { status: 204 }) : new Response("[]", { status: 200 });
  };
  try {
    await api.listNarrativeProjects("workspace", { trashed: true, limit: 100 });
    await api.renameNarrativeProject("workspace", "a/b", "New name");
    await api.trashNarrativeProject("workspace", "project", "head", true);
    await api.trashNarrativeProject("workspace", "project", "head", false);
    await api.narrativeProjectContents("workspace", "project");
    assert.equal(await api.deleteNarrativeProject("workspace", "project"), undefined);
  } finally { globalThis.fetch = original; }
  const list = new URL(calls[0].path, "http://test");
  assert.equal(list.searchParams.get("trashed"), "true");
  assert.equal(calls[1].path, "/v1/narrative/projects/a%2Fb/rename");
  assert.deepEqual(JSON.parse(calls[1].init.body), { name: "New name" });
  assert.equal(calls[2].path, "/v1/narrative/projects/project/archive");
  assert.deepEqual(JSON.parse(calls[2].init.body), { base_revision_id: "head", archived: true });
  assert.deepEqual(JSON.parse(calls[3].init.body), { base_revision_id: "head", archived: false });
  assert.equal(calls[4].path, "/v1/narrative/projects/project/contents");
  assert.equal(calls[5].init.method, "DELETE");
  assert.equal(calls[5].path, "/v1/narrative/projects/project");
  for (const call of calls) assert.equal(call.init.headers["X-Tenant-ID"], "workspace");
});
