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


async def test_parent_refuses_weights_with_a_mismatched_training_reference(tmp_path):
    blob = weights()
    helper = tmp_path / "conditioning.py"
    helper.write_text("# trusted fixture\n")
    helper_hash = hashlib.sha256(helper.read_bytes()).hexdigest()
    source = b"approved reference"
    source_hash = hashlib.sha256(source).hexdigest()
    script = tmp_path / "train.py"
    script.write_text(
        "import sys,json,pathlib\nr=json.load(sys.stdin)\n"
        "assert r['schema_version']==2 and r['reference_index']==3\n"
        "pathlib.Path('out').mkdir()\npathlib.Path('out/adapter.safetensors').write_bytes("
        + repr(blob)
        + ")\nprint(json.dumps({'event':'result','sha256':'"
        + hashlib.sha256(blob).hexdigest()
        + "','losses':[1.0]*20,'runtime':{'conditioning':'approved_look_image',"
        "'loss_tokens':'target_only','reference_sha256':'"
        + "0" * 64
        + "','conditioning_sha256':'"
        + helper_hash
        + "'}}),flush=True)"
    )
    trainer = LocalStyleTrainer(
        python=Path(sys.executable),
        script=script,
        model_dir=tmp_path,
        model_hash="b" * 64,
        deadline=10,
    )
    request = StyleTrainingRequest(
        images=(
            *((b"image" + bytes([i]), "navy coat") for i in range(3)),
            (source, "approved coat"),
        ),
        dataset_hash="c" * 64,
        recipe_hash="d" * 64,
        trigger="fgstyle_qa",
        steps=20,
        seed=42,
        reference_index=3,
    )

    async def update(_step):
        pass

    with pytest.raises(ValueError, match="invalid_output"):
        await trainer.train(request, on_progress=update)
    script.write_text(script.read_text().replace("0" * 64, source_hash))
    assert (await trainer.train(request, on_progress=update)).runtime[
        "reference_sha256"
    ] == source_hash
