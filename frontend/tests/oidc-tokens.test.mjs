import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/oidcTokens.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const model = await import(
  `data:text/javascript;base64,${Buffer.from(outputText + "\n//# sourceURL=oidc-tokens.js").toString("base64")}`
);

const user = { access_token: "access", id_token: "identity", expired: false };

test("the access token stays the default, so other providers are unchanged", () => {
  for (const configured of [undefined, "", "access_token", "anything else"]) {
    assert.equal(model.bearerKind(configured), "access_token");
  }
  assert.equal(model.bearerToken(user, "access_token"), "access");
});

test("a deployment can ask for the ID token, which is what carries Cognito's audience and email", () => {
  assert.equal(model.bearerKind("id_token"), "id_token");
  assert.equal(model.bearerToken(user, "id_token"), "identity");
});

test("nobody signed in, an expired session or a missing ID token sends nothing", () => {
  assert.equal(model.bearerToken(null, "id_token"), null);
  assert.equal(model.bearerToken(undefined, "access_token"), null);
  assert.equal(model.bearerToken({ ...user, expired: true }, "id_token"), null);
  assert.equal(model.bearerToken({ ...user, expired: true }, "access_token"), null);
  assert.equal(model.bearerToken({ access_token: "access" }, "id_token"), null);
});

test("Cognito's sign-out page gets the client and where to come back to", () => {
  const address = new URL(
    model.logoutAddress("https://sign-in.example.com/logout", "client-1", "https://studio.example.com"),
  );
  assert.equal(address.pathname, "/logout");
  assert.equal(address.searchParams.get("client_id"), "client-1");
  assert.equal(address.searchParams.get("logout_uri"), "https://studio.example.com");
});

test("providers with an end-session endpoint keep using it", () => {
  assert.equal(model.logoutAddress(undefined, "client-1", "https://studio.example.com"), null);
  assert.equal(model.logoutAddress("", "client-1", "https://studio.example.com"), null);
  assert.equal(model.logoutAddress("https://sign-in.example.com/logout", undefined, "https://x.example"), null);
});

test("a person is shown by name, or by email when the provider has no name", () => {
  assert.equal(model.displayName({ name: "Mio", email: "mio@example.com" }), "Mio");
  assert.equal(model.displayName({ email: "mio@example.com" }), "mio@example.com");
  assert.equal(model.displayName({}), null);
  assert.equal(model.displayName(undefined), null);
});
