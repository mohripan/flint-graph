// Browser-only regression fixture. It mounts production components against a synthetic API.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "../../src/lib/api";
import { ProposalActions } from "../../src/narrative/ProposalActions";
import { AssetLibrary } from "../../src/narrative/AssetLibrary";
import { CharacterProfilesContext } from "../../src/narrative/characterImages";
import { SceneStage } from "../../src/narrative/StageEditor";
import "../../src/index.css";
import "../../src/narrative/studio.css";
import "../../src/narrative/assistant.css";

const artwork = new Blob([`<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#1e344c"/><circle cx="1080" cy="100" r="50" fill="#eee3b0"/><path d="M0 300H1280V720H0Z" fill="#497458"/><path d="M460 720L580 300H700L820 720" fill="#bdab8d"/></svg>`], { type: "image/svg+xml" });
const asset = { id: "courtyard", name: "Courtyard", kind: "background", status: "approved", media_type: "image/png", sha256: "a".repeat(64), width: 1280, height: 720, license: "cc0", created_at: "2026-10-31T00:00:00Z" };
const generated = Array.from({ length: 4 }, (_, index) => ({ ...asset, id: `generated-${index}`, name: `Generated courtyard ${index + 1}`, status: "candidate" }));
const story = { schema_version: "2", id: "fixture", title: "Fixture", language: "en", entry: "ending", characters: {}, variables: {},
  assets: { courtyard: { kind: "image", path: "assets/courtyard.png", sha256: asset.sha256 } },
  nodes: { ending: { type: "end", text_id: "ending", text: "Fin.", ending: "done" } } };
const proposal = { id: "fixture-proposal", status: "accepted", operations: [{ op: "generate_backgrounds", description: "courtyard at night" }] };
const read = () => JSON.parse(localStorage.getItem("assistant-image-fixture") ?? "null");
let job = read();
let starts = Number(localStorage.getItem("assistant-image-fixture-starts") ?? 0);
api.listAssistantImageActions = async () => [{ index: 0, job }];
api.startAssistantImageAction = async () => {
  if (!job) {
    starts += 1; localStorage.setItem("assistant-image-fixture-starts", String(starts));
    job = { id: "fixture-job", purpose: "background", status: "running", progress: 1, count: 4, cancel_requested: false, created_at: "2026-10-31T00:00:00Z", assets: [] };
    localStorage.setItem("assistant-image-fixture", JSON.stringify(job));
  }
  await new Promise(resolve => setTimeout(resolve, 500));
  return job;
};
api.listBackgroundJobs = async () => ({ jobs: job ? [job] : [] });
api.listNarrativeAssets = async (_tenant, _project, query) => ({ assets: query?.status === "approved" ? [asset]
  : query?.status === "candidate" ? (job?.status === "completed" ? generated : [])
  : [asset, ...(job?.status === "completed" ? generated : [])], next_before: null });
api.getNarrativeImage = async () => artwork;
window.fixtureState = () => ({ starts, job });
function Fixture() {
  const [view, setView] = useState("Assistant");
  return <main style={{ maxWidth: 1180, margin: "30px auto", padding: 24 }}>
    <h1>Assistant image regression fixture</h1>
    <nav>{["Assistant", "Assets", "Stage"].map(name => <button key={name} onClick={() => setView(name)}>{name}</button>)}</nav>
    <button onClick={() => { job = { ...job, status: "completed", progress: 4, assets: generated }; localStorage.setItem("assistant-image-fixture", JSON.stringify(job)); }}>Complete fixture job</button>
    <CharacterProfilesContext.Provider value={{ tenantId: "fixture", projectId: "fixture", profiles: {}, put: () => {}, reload: async () => {} }}>
      {view === "Assistant" && <ProposalActions proposal={proposal} story={story} tenantId="fixture" projectId="fixture" canWrite />}
      {view === "Assets" && <AssetLibrary tenantId="fixture" projectId="fixture" canWrite />}
      {view === "Stage" && <SceneStage story={story} head="ending" inherited={{ background: "courtyard", cg: null, characters: {} }} readOnly={false}
        onChange={() => { throw new Error("Reading inherited state must not edit the story"); }} onError={error => { throw new Error(error); }} />}
    </CharacterProfilesContext.Provider>
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
