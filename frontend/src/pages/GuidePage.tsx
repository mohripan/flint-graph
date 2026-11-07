import { linkProps } from "../site/router";
import { GuideSteps } from "../narrative/GettingStarted";

// The same steps as the first-time panel, plus the questions people ask once they have started.
export function GuidePage() {
  return (
    <div className="h-full overflow-auto p-6">
      <div className="mx-auto max-w-3xl space-y-8">
        <header>
          <h1 className="text-xl font-semibold text-slate-900">Guide</h1>
          <p className="mt-1 text-sm text-slate-500">One way through the Studio, from an empty page to a game someone can play.</p>
        </header>
        <section className="studio-guide" aria-label="Steps"><GuideSteps /></section>
        <section className="space-y-4 text-sm text-slate-600" aria-labelledby="guide-questions">
          <h2 id="guide-questions" className="font-semibold text-slate-900">Good to know</h2>
          <div>
            <h3 className="font-medium text-slate-800">What are credits?</h3>
            <p className="mt-1">Pictures, voices, assistant replies and release builds use credits, and the cost is shown before anything starts. Writing, editing and playtesting are free. Your balance is at the top of the page, and Usage shows where it went.</p>
          </div>
          <div>
            <h3 className="font-medium text-slate-800">Why does it sometimes take a while to start?</h3>
            <p className="mt-1">The computer that makes pictures and voices may be asleep to save money. When it is, the Studio tells you before you start.</p>
          </div>
          <div>
            <h3 className="font-medium text-slate-800">Can I undo what the Assistant does?</h3>
            <p className="mt-1">Yes. Its changes only happen when you press Accept, and every saved version stays under History.</p>
          </div>
          <div>
            <h3 className="font-medium text-slate-800">Can I show the Assistant what I see?</h3>
            <p className="mt-1">Yes. Paste a screenshot into the chat, drop a file there, or press Picture. It reads what is on screen and answers about it.</p>
          </div>
          <div>
            <h3 className="font-medium text-slate-800">How do I delete a project?</h3>
            <p className="mt-1">Choose Move to trash on its card. It stays in the Trash, safe and restorable, until you choose Delete forever.</p>
          </div>
          <p><a {...linkProps("/how-it-works")} className="underline underline-offset-2 hover:text-slate-900">Read more about how it works</a></p>
        </section>
      </div>
    </div>
  );
}
