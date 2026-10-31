"""Build a local page to rate voice-model samples (#174, ADR 0044).

    uv run python tools/narrative/voice_rating_page.py --runs notes/voice-eval/user \
        --reference voice_recording.wav --out notes/voice-eval/rate.html

Reads the ``*-bench.json`` files that tools/narrative/voice_bench.py wrote and embeds
every clip and the reference as data URIs, so the page works offline from disk and
nothing is uploaded: the clips may be a real person's voice. Raters score voice
similarity per model and how well each clip carries its delivery, then copy the
ratings as JSON.
"""

import argparse
import base64
import html
import json
from pathlib import Path

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Voice model ratings</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;margin:24px;background:#f4f6f8;color:#182635}}
table{{border-collapse:collapse;background:#fff;width:100%}}
td,th{{border:1px solid #d6dde3;padding:8px;vertical-align:top}}
th{{background:#e9eef2;text-align:left}}audio{{width:220px}}select{{margin-top:4px}}
textarea{{width:100%;height:120px}}.muted{{color:#5b6b78;font-size:13px}}
</style></head><body>
<h1>Voice model ratings</h1>
<p>Listen to the reference, then rate each model: <b>similarity</b> (does it sound like
the reference speaker?) and, per line, <b>delivery</b> (does it sound like the named
delivery?). 1 = not at all, 5 = convincingly. Leave a cell empty if a clip failed. When
done, press <b>Copy ratings</b> and paste them into the chat.</p>
<p><b>Reference</b><br><audio controls src="{reference}"></audio></p>
<table><thead><tr><th>Line</th>{heads}</tr></thead><tbody>
<tr><th>Similarity to the reference</th>{similarity}</tr>
{rows}
</tbody></table>
<p><button id="copy">Copy ratings</button> <span id="copied" class="muted"></span></p>
<textarea id="out" readonly></textarea>
<script>
const collect = () => {{
  const ratings = {{}};
  document.querySelectorAll("select[data-model]").forEach(el => {{
    if (!el.value) return;
    (ratings[el.dataset.model] ??= {{}})[el.dataset.key] = Number(el.value);
  }});
  return JSON.stringify(ratings);
}};
const note = text => {{ document.getElementById("copied").textContent = text; }};
document.addEventListener("change", () => {{ document.getElementById("out").value = collect(); }});
document.getElementById("copy").onclick = async () => {{
  const text = collect();
  document.getElementById("out").value = text;
  try {{ await navigator.clipboard.writeText(text); note("Copied."); }}
  catch {{ note("Select the text below and copy it."); }}
}};
</script></body></html>
"""
LINES = [
    "neutral",
    "happy",
    "angry",
    "sad",
    "afraid",
    "surprised",
    "whisper",
    "shout",
    "dramatic",
    "tender",
    "vocalization",
    "ja",
]


def data_uri(path: Path) -> str:
    return "data:audio/wav;base64," + base64.b64encode(path.read_bytes()).decode()


def select(model: str, key: str) -> str:
    options = "".join(f'<option value="{n}">{n}</option>' for n in range(1, 6))
    blank = '<option value=""></option>'
    return f'<select data-model="{model}" data-key="{key}">{blank}{options}</select>'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    benches = [json.loads(path.read_text()) for path in sorted(args.runs.glob("*-bench.json"))]
    models = sorted({bench["model"] for bench in benches})
    clips: dict[tuple[str, str], Path] = {}
    for bench in benches:
        for clip in bench["clips"]:
            clips[(bench["model"], clip["delivery"])] = args.runs / clip["file"]
    heads = "".join(f"<th>{html.escape(model)}</th>" for model in models)
    similarity = "".join(f"<td>{select(model, 'similarity')}</td>" for model in models)
    rows = []
    for line in LINES:
        cells = []
        for model in models:
            path = clips.get((model, line))
            cells.append(
                f'<td><audio controls preload="none" src="{data_uri(path)}"></audio><br>'
                f"{select(model, line)}</td>"
                if path
                else '<td class="muted">not offered</td>'
            )
        if any("<audio" in cell for cell in cells):
            rows.append(f"<tr><th>{html.escape(line)}</th>{''.join(cells)}</tr>")
    page = PAGE.format(
        reference=data_uri(args.reference),
        heads=heads,
        similarity=similarity,
        rows="\n".join(rows),
    )
    args.out.write_text(page, encoding="utf-8")
    print(f"wrote {args.out} ({len(page) // 1024} KiB, {len(models)} models)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
