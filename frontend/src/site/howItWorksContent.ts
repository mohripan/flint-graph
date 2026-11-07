// The "How it works" page copy. Describe only features the Studio has delivered.

export type Step = { title: string; body: string[]; image?: { src: string; alt: string } };

export const STEPS: Step[] = [
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
      "Open the Assistant and describe what you want in plain words: a new scene, a rewrite, a character, a change to the stage or the text box. You can watch it work as it reads your story, drafts the changes and checks them against the story's rules.",
      "It replies with a proposal you can read change by change. Nothing in your story changes until you accept it. If something important is missing, such as a character's name or outfit, it asks first. When something needs generating, such as a picture or a voice, a card in the chat shows what it will make and what it costs, and nothing runs until you press Generate.",
    ],
  },
  {
    title: "Cast your characters",
    body: [
      "Describe a character and generate candidates: a portrait, or a full-body sprite with a transparent background, drawn at high resolution so it stays sharp on a large stage.",
      "Approve the one that fits. That approved look becomes the reference for expressions, poses and event art, so the character stays recognizable.",
    ],
  },
  {
    title: "Add expressions and poses",
    body: [
      "Expressions repaint only the face of an approved sprite: happy, embarrassed, smug, sleepy and more, or your own words. The rest of the picture stays exactly the same, so a character doesn't jump on stage when their expression changes.",
      "Poses redraw the character from the approved look with an instruction such as “sitting on a bench, waving”. Compare each candidate with the look, approve the ones that keep the face and outfit, and use them on the stage. You can also train a private art style or character look from 4 to 12 of your approved images. It stays in your project and never ships in a game.",
    ],
  },
  {
    title: "Draw backgrounds and event CGs",
    body: [
      "Generate locations from a short description, or upload your own art and note your right to use it. Folders and automatic groups by kind and character keep the library tidy.",
      "Event CGs are full-scene illustrations of a key moment. Pick one or two characters and describe the scene, and each character is drawn from an approved image of them. Two-character CGs are still experimental, so you get eight candidates to choose from. Players can revisit every CG they've seen in the game's gallery.",
    ],
    image: { src: "/site/cg-candidates.webp", alt: "Generated event CG candidates of one character, waiting for approval" },
  },
  {
    title: "Set the stage",
    body: [
      "Choose a background or event CG for each scene, place characters and decide how large they stand, and pick each line's expression. The Look tab styles the text box, name tag, choices and font.",
    ],
    image: { src: "/site/stage-editor.webp", alt: "The scene editor with the stage, an event CG, character placement and voiced lines" },
  },
  {
    title: "Give lines a voice",
    body: [
      "A line can be fully voiced, carry a short sound such as “hmm” or “fufu”, or stay silent. Give each character a stock voice, or clone one from a 5 to 30 second recording made with the speaker's consent. You can also upload your own WAV clips.",
      "Delivery follows the line's expression, such as angry, tender or whispered, and you can change it line by line. Some voice models come with license terms: you accept them once, and their credits and terms go into your game automatically.",
    ],
  },
  {
    title: "Playtest and release",
    body: [
      "Play any saved revision in the browser. When it's ready, build a release: a web game you can share, or an editable Godot project you download and own. Credits and licenses for the art and voices you used are included automatically.",
    ],
    image: { src: "/site/two-characters.webp", alt: "A playtest with two characters in an event illustration" },
  },
];

export const FAQ: Array<[string, string]> = [
  ["Who can join?", "Anyone with an invitation key or an email invitation. If you would like one, email ripan@flintgraph.digital."],
  ["Can I use my work email?", "Yes, but you don't have to. A key works with any account. An email invitation needs the exact address it was sent to, verified by your sign-in provider."],
  ["Is there a limit on generating?", "Each invitation includes credits. Generating spends them: a standard image or a simple voice line costs little, while a pose, a CG, a release build or a training run costs more, and the Studio shows the price before you start. There are also daily caps on how much you can make. If you run out of either, the Studio says which. Chatting with the assistant spends a little too, because it runs on the same GPU. Writing, editing and playtesting are free."],
  ["Who owns what I make?", "Your stories and the art and voices you approve are yours to use in your game. Exported Godot projects are ordinary source projects you can keep editing."],
];
