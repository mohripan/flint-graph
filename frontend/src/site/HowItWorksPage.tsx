import { linkProps } from "./router";
import { FAQ, STEPS } from "./howItWorksContent";
import { Screenshot, SiteLayout } from "./SiteLayout";

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
