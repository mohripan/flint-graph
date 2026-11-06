import { linkProps } from "./router";
import { Screenshot, SiteLayout } from "./SiteLayout";

const FEATURES: Array<{ title: string; body: string; mark: string }> = [
  { mark: "✎", title: "A branching story editor",
    body: "Write scenes as script, add choices, conditions and endings, and see every route on a map." },
  { mark: "✦", title: "An assistant that proposes",
    body: "Describe a change in chat. The assistant drafts it as a reviewable proposal; nothing changes until you accept." },
  { mark: "☺", title: "Characters that stay themselves",
    body: "Approve a look once, then make expressions and poses from it. Every generated picture waits for your approval." },
  { mark: "▣", title: "Backgrounds and event CGs",
    body: "Generate locations and full-scene illustrations of your cast, then place them on the stage." },
  { mark: "♪", title: "Voices with feeling",
    body: "Give lines a voice: full speech or a short “hmm”, with delivery such as angry, tender or whispered." },
  { mark: "▶", title: "Playtest and ship",
    body: "Play any saved revision in the browser, then build a web game or download an editable Godot project." },
];

export function HomePage() {
  return (
    <SiteLayout current="home">
      <section className="site-hero text-white">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 pt-16 pb-20 sm:px-6 lg:grid-cols-[1fr_1.1fr] lg:pt-24 lg:pb-28">
          <div>
            <p className="mb-4 inline-flex rounded-full border border-amber-300/30 bg-amber-300/10 px-3 py-1 text-xs font-semibold tracking-wide text-amber-200 uppercase">
              Visual-novel studio · invite-only preview
            </p>
            <h1 className="site-serif text-4xl leading-tight font-semibold sm:text-5xl xl:text-6xl">
              <span className="block whitespace-nowrap">Write it. Draw it.</span>
              <span className="block whitespace-nowrap">Voice it. Ship it.</span>
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-slate-300">
              FlintGraph is a studio for branching visual novels. Write scenes with an assistant, generate
              characters, backgrounds, event art and voices, playtest in a click, and export a Godot game you can keep editing.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <a {...linkProps("/join")} className="rounded-lg bg-amber-400 px-5 py-3 font-semibold text-slate-950 shadow-xs transition hover:bg-amber-300">
                Join with an invitation
              </a>
              <a {...linkProps("/how-it-works")} className="rounded-lg border border-white/25 px-5 py-3 font-semibold text-white transition hover:bg-white/10">
                See how it works
              </a>
            </div>
          </div>
          <div className="site-frame overflow-hidden rounded-2xl bg-slate-900">
            <div className="flex items-center gap-1.5 border-b border-white/10 px-4 py-2.5" aria-hidden="true">
              <span className="h-2.5 w-2.5 rounded-full bg-red-400/80" /><span className="h-2.5 w-2.5 rounded-full bg-amber-400/80" />
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-400/80" />
              <span className="ml-3 text-xs text-slate-400">Playtest · revision 3</span>
            </div>
            <img src="/site/playtest.webp" alt="A playtest: a white-haired character on a window seat at night, with a dialogue box reading “The lanterns are lit again.”"
              className="w-full" width={720} height={527} />
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6" aria-labelledby="features">
        <div className="max-w-2xl">
          <h2 id="features" className="site-serif text-3xl font-semibold sm:text-4xl">One studio, from first line to finished game</h2>
          <p className="mt-4 text-lg text-slate-600">Everything a visual novel needs lives in one project, with every change saved as a revision you can return to.</p>
        </div>
        <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(feature => (
            <article key={feature.title} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <span aria-hidden="true" className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-50 text-lg text-amber-700">{feature.mark}</span>
              <h3 className="mt-4 text-lg font-semibold">{feature.title}</h3>
              <p className="mt-2 leading-relaxed text-slate-600">{feature.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="border-y border-slate-200 bg-white" aria-labelledby="showcase">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <h2 id="showcase" className="site-serif text-3xl font-semibold sm:text-4xl">See it in the Studio</h2>
          <div className="mt-10 grid gap-8 lg:grid-cols-3">
            <figure>
              <Screenshot src="/site/stage-editor.webp" alt="The scene editor: a scene list, the stage with an event CG, character placement and voiced dialogue lines" className="site-shot aspect-[4/3] object-cover object-top" />
              <figcaption className="mt-3 text-sm text-slate-600"><strong className="text-slate-900">Direct the stage.</strong> Backgrounds, CGs, who stands where, and each line's voice.</figcaption>
            </figure>
            <figure>
              <Screenshot src="/site/cg-candidates.webp" alt="Four generated event CG candidates of the same character, each waiting to be approved" className="site-shot aspect-[4/3] object-cover object-top" />
              <figcaption className="mt-3 text-sm text-slate-600"><strong className="text-slate-900">Review every picture.</strong> Generated art arrives as candidates; you choose what joins the story.</figcaption>
            </figure>
            <figure>
              <Screenshot src="/site/two-characters.webp" alt="A playtest showing two characters together in an event illustration" className="site-shot aspect-[4/3] object-cover object-top" />
              <figcaption className="mt-3 text-sm text-slate-600"><strong className="text-slate-900">Play it right away.</strong> Every saved revision plays in the browser, exactly as players will see it.</figcaption>
            </figure>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6" aria-labelledby="preview">
        <div className="site-hero grid gap-8 overflow-hidden rounded-3xl px-6 py-12 text-white sm:px-12 lg:grid-cols-[1.4fr_1fr] lg:items-center">
          <div>
            <h2 id="preview" className="site-serif text-3xl font-semibold">An invite-only preview</h2>
            <p className="mt-4 max-w-xl leading-relaxed text-slate-300">
              FlintGraph is opening to a small group first. If you received an invitation key, or an invitation
              sent to your email address, you can join now. Each invitation includes a generous daily allowance
              of images, voice lines and assistant replies.
            </p>
          </div>
          <div className="flex flex-wrap gap-3 lg:justify-end">
            <a {...linkProps("/join")} className="rounded-lg bg-amber-400 px-5 py-3 font-semibold text-slate-950 transition hover:bg-amber-300">I have an invitation</a>
            <a {...linkProps("/how-it-works")} className="rounded-lg border border-white/25 px-5 py-3 font-semibold transition hover:bg-white/10">How joining works</a>
          </div>
        </div>
      </section>
    </SiteLayout>
  );
}
