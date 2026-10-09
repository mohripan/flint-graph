import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/queryOutcome.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext },
});
const { queryFailureMessage } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

test("a support failure displays the persisted operation-specific message", () => {
  assert.equal(queryFailureMessage({
    status: "failed", error_message: "The support checker could not verify the answer.",
  }), "The support checker could not verify the answer.");
});

test("cancellation is an explicit incomplete outcome", () => {
  assert.equal(queryFailureMessage({ status: "cancelled" }),
    "The query was cancelled before an answer was finalized.");
});

test("an unfinished stream cannot become an empty successful answer", () => {
  assert.equal(queryFailureMessage({ status: "running" }),
    "The connection closed before the query finished. Check query history for its status.");
});

test("completed runs can show their verified answer or evidence abstention", () => {
  assert.equal(queryFailureMessage({ status: "completed" }), null);
});
