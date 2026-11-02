import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/narrative/lookModel.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const model = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

test("locking a look preserves the selected approved reference and reviewed tags", () => {
  const body = model.lookRequest({ name: " Travel coat ", assetId: "a", identity: "white_hair, red eyes, white hair",
    clothes: "navy coat, red scarf", baseVersion: 3, parentId: "previous", key: "key" });
  assert.deepEqual(body, { name: "Travel coat", asset_id: "a", identity_tags: ["white hair", "red eyes"],
    clothing_tags: ["navy coat", "red scarf"], base_version: 3, parent_look_id: "previous", idempotency_key: "key" });
});

test("reference choices exclude other characters, candidates, CGs and non-images", () => {
  const asset = (id, changes = {}) => ({ id, character_id: "mira", status: "approved", kind: "sprite", media_type: "image/png", provenance: {}, ...changes });
  assert.deepEqual(model.lookReferences([asset("yes"), asset("other", {character_id:"other"}),
    asset("pending", {status:"candidate"}), asset("cg", {provenance:{ip_adapter:{}}}),
    asset("sound", {media_type:"audio/wav"}), asset("upload", {character_id:null,kind:"image"})], "mira").map(a => a.id), ["yes", "upload"]);
});

test("a character's own approved image is offered before unassigned uploads", () => {
  const asset = (id, character_id) => ({id,character_id,status:"approved",kind:"image",media_type:"image/png",provenance:{}});
  assert.deepEqual(model.lookReferences([asset("unassigned",null),asset("own","mira")], "mira").map(item=>item.id), ["own","unassigned"]);
});

test("anatomy warnings survive matching identity and clothes and apply to duplicate image bytes", () => {
  const asset={id:'new-copy',sha256:'same-bytes'};
  const flag={asset_id:'old-copy',candidate_sha256:'same-bytes',look_id:'look',identity:'same',clothes:'same',anatomy:'flawed'};
  assert.deepEqual(model.reviewWarnings(asset,[flag]),[{...flag,reasons:['Review anatomy']}]);
  assert.deepEqual(model.anatomyFailures([asset],[flag]),new Set(['new-copy']));
  assert.deepEqual(model.reviewWarnings({...asset,sha256:'different'},[flag]),[]);
  assert.deepEqual(model.reviewWarnings(asset,[{...flag,anatomy:'unknown'}]),[]);
  assert.deepEqual(model.feedbackBody({version:1,identity:'same',clothes:'same',notes:'legacy'}),{base_version:1,identity:'same',clothes:'same',notes:'legacy'});
  assert.equal(model.feedbackBody({version:2,identity:'same',clothes:'same',notes:'',anatomy:'flawed'}).anatomy,'flawed');
  assert.equal(model.feedbackBody({version:2,identity:'same',clothes:'same',notes:'',anatomy:'flawed',anatomy_version:4}).anatomy_base_version,4);
});
