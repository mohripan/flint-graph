import hashlib
import sys
from pathlib import Path

import pytest
from test_narrative_style_weights import weights

from flint_graph.infrastructure.narrative_stylegen import LocalStyleTrainer, StyleTrainingRequest


async def test_isolated_trainer_validates_weights_and_reports_progress(tmp_path):
    blob = weights()
    script = tmp_path / "train.py"
    script.write_text(
        "import sys,json,pathlib\nr=json.load(sys.stdin)\nassert len(r['images'])==4\n"
        "pathlib.Path('out').mkdir()\n"
        "pathlib.Path('out/adapter.safetensors').write_bytes("
        + repr(blob)
        + ")\nprint(json.dumps({'event':'progress','step':1,'loss':1.0}),flush=True)\n"
        "print(json.dumps({'event':'result','sha256':'"
        + hashlib.sha256(blob).hexdigest()
        + "','losses':[1.0]*20,'runtime':{'seconds':'1'}}),flush=True)"
    )
    progress = []

    async def update(step):
        progress.append(step)

    trainer = LocalStyleTrainer(
        python=Path(sys.executable),
        script=script,
        model_dir=tmp_path,
        model_hash="b" * 64,
        deadline=10,
    )
    request = StyleTrainingRequest(
        images=tuple((b"image" + bytes([i]), "navy coat") for i in range(4)),
        dataset_hash="c" * 64,
        recipe_hash="d" * 64,
        trigger="fgstyle_qa",
        steps=20,
        seed=42,
    )
    result = await trainer.train(request, on_progress=update)
    assert result.weights == blob and len(result.losses) == 20 and progress == [1]
    script.write_text(
        script.read_text().replace(
            "'" + hashlib.sha256(blob).hexdigest() + "'", "'" + "f" * 64 + "'"
        )
    )
    with pytest.raises(ValueError, match="invalid_output"):
        await trainer.train(request, on_progress=update)
