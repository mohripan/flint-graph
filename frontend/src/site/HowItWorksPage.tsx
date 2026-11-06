import { linkProps } from "./router";
import { Screenshot, SiteLayout } from "./SiteLayout";

const STEPS: Array<{ title: string; body: string[]; image?: { src: string; alt: string } }> = [
  {
    title: "Join with an invitation",
    body: [
      "FlintGraph is invite-only for now. You join in one of two ways: with an invitation key, or with an invitation sent to your email address.",
      "A key works with any account you sign in with, so you can use it even if you were contacted at a shared company address. An email invitation is matched to your verified address automatically.",
    ],
  },
  {
    title: "Write your story",
    body: [
      "Create a project and write scenes as script: who speaks, what they say, which choices follow. Conditions and endings shape the routes, and the map shows every path through the story.",
      "Every save becomes a revision, so you can always look back or start again from an earlier version.",
    ],
  },
  {
    title: "Ask the assistant",
    body: [
      "Describe what you want in plain words: a new scene, a rewrite, a character. The assistant replies with a proposal you can read change by change. Nothing in your story changes until you accept it.",
    ],
  },
  {
    title: "Cast your characters",
    body: [
      "Describe a character and generate candidates. Approve the one that fits, and that approved look becomes the reference for expressions, poses and event art, so the character stays recognizable.",
    ],
    image: { src: "/site/cg-candidates.webp", alt: "Generated event CG candidates of one character, waiting for approval" },
  },
  {
    title: "Set the stage and give lines a voice",
    body: [
      "Choose backgrounds and event CGs, place characters on the stage, and pick a look for the text box. Lines can be fully voiced, carry a short sound such as “hmm”, or stay silent.",
    ],
    image: { src: "/site/stage-editor.webp", alt: "The scene editor with the stage, an event CG, character placement and voiced lines" },
  },
  {
    title: "Playtest and release",
    body: [
      "Play any saved revision in the browser. When it's ready, build a release: a web game you can share, or an editable Godot project you download and own. Credits and licenses for the art and voices you used are included automatically.",
    ],
    image: { src: "/site/two-characters.webp", alt: "A playtest with two characters in an event illustration" },
  },
];

const FAQ: Array<[string, string]> = [
  ["Who can join?", "Anyone with an invitation key or an email invitation. If you would like one, ask the person who told you about FlintGraph."],
  ["Can I use my work email?", "Yes, but you don't have to. A key works with any account. An email invitation needs the exact address it was sent to, verified by your sign-in provider."],
  ["Is there a limit on generating?", "Each invitation includes an allowance per day and in total, for images, voice lines, assistant replies, releases and training runs. If you reach one, the Studio says which and when it resets. Writing, editing and playtesting are never limited."],
  ["Who owns what I make?", "Your stories and the art and voices you approve are yours to use in your game. Exported Godot projects are ordinary source projects you can keep editing."],
];

export function HowItWorksPage() {
  return (
    <SiteLayout current="how">
      <section className="site-hero text-white">
        <div className="mx-auto max-w-4xl px-4 py-16 sm:px-6 lg:py-20">
          <p className="text-sm font-semibold tracking-wide text-amber-200 uppercase">How it works</p>
          <h1 className="site-serif mt-3 text-4xl font-semibold sm:text-5xl">From an idea to a playable visual novel</h1>
          <p className="mt-5 max-w-2xl text-lg text-slate-300">
            FlintGraph keeps writing, art, voices and releases in one place. Here is the path a story takes.
          </p>
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-4 py-16 sm:px-6" aria-label="Steps">
        <ol className="space-y-16">
          {STEPS.map((step, index) => (
            <li key={step.title} className={`grid gap-8 ${step.image ? "lg:grid-cols-2 lg:items-center" : ""}`}>
              <div className={step.image && index % 2 === 1 ? "lg:order-2" : ""}>
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold text-amber-300">{index + 1}</span>
                <h2 className="site-serif mt-4 text-2xl font-semibold sm:text-3xl">{step.title}</h2>
                {step.body.map(text => <p key={text} className="mt-3 max-w-2xl leading-relaxed text-slate-600">{text}</p>)}
              </div>
              {step.image && <Screenshot src={step.image.src} alt={step.image.alt} className="site-shot" />}
            </li>
          ))}
        </ol>
      </section>

      <section className="border-t border-slate-200 bg-white" aria-labelledby="faq">
        <div className="mx-auto max-w-4xl px-4 py-16 sm:px-6">
          <h2 id="faq" className="site-serif text-3xl font-semibold">Questions</h2>
          <dl className="mt-8 divide-y divide-slate-200">
            {FAQ.map(([question, answer]) => (
              <div key={question} className="py-5">
                <dt className="font-semibold">{question}</dt>
                <dd className="mt-2 leading-relaxed text-slate-600">{answer}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-10 flex flex-wrap gap-3">
            <a {...linkProps("/join")} className="rounded-lg bg-slate-900 px-5 py-3 font-semibold text-white transition hover:bg-slate-800">Join with an invitation</a>
            <a {...linkProps("/")} className="rounded-lg border border-slate-300 px-5 py-3 font-semibold text-slate-700 transition hover:bg-slate-50">Back to the overview</a>
          </div>
        </div>
      </section>
    </SiteLayout>
  );
}
