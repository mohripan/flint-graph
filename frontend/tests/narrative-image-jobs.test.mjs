import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source = await readFile(new URL("../src/narrative/imageJobModel.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const model = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
test("late lists cannot regress a started job and terminal jobs stay terminal", () => {
  const job = (id, status, progress = 0) => ({ id, status, progress, cancel_requested: false, created_at: "2026-10-31T00:00:00Z" });
  let jobs = model.mergeImageJobs([job("a", "running", 2)], [job("a", "queued")]);
  assert.equal(jobs[0].status, "running"); assert.equal(jobs[0].progress, 2);
  jobs = model.mergeImageJobs(jobs, [job("a", "completed", 4), job("b", "queued")]);
  jobs = model.mergeImageJobs(jobs, [job("a", "running", 3)]);
  assert.equal(jobs.find(j => j.id === "a").status, "completed");
  assert.equal(jobs.find(j => j.id === "b").status, "queued");
});
