import { useState } from "react";
import { GUIDE_STEPS, guideSeen, markGuideSeen } from "./guideModel";

const storage = () => { try { return window.localStorage; } catch { return null; } };

export function GuideSteps() {
  return <ol className="studio-guide-steps">{GUIDE_STEPS.map(step => <li key={step.title}>
    <h3>{step.title}</h3><p>{step.text}</p></li>)}</ol>;
}

/** Shown on the project list until it is dismissed. Guide in the sidebar always brings it back. */
export function GettingStarted() {
  const [hidden, setHidden] = useState(() => guideSeen(storage()));
  if (hidden) return null;
  return <section className="studio-guide" aria-labelledby="studio-guide-title">
    <h2 id="studio-guide-title">New here? This is how a game gets made</h2>
    <GuideSteps />
    <div className="studio-guide-foot">
      <p className="studio-hint">You can read this again any time under Guide in the sidebar.</p>
      <button type="button" className="studio-primary" onClick={() => { markGuideSeen(storage()); setHidden(true); }}>Got it</button>
    </div>
  </section>;
}
