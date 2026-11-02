"""The pose child is isolated, bounded and checked before images are published."""

import struct
import sys
import zlib
from pathlib import Path

import pytest

from flint_graph.infrastructure.narrative_imagegen import ImageGenerationError, ModelIdentity
from flint_graph.infrastructure.narrative_posegen import LocalPoseGenerator, PoseGenerationRequest
from flint_graph.narrative.poses import MODEL_REPO, MODEL_REVISION

FAKE = """  # noqa: E501
import json,sys,struct,zlib
from pathlib import Path
r=json.load(sys.stdin)
def png(w,h):
 def chunk(k,p):return struct.pack('>I',len(p))+k+p+struct.pack('>I',zlib.crc32(k+p))
 return (b'\\x89PNG\\r\\n\\x1a\\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))
  +chunk(b'IDAT',zlib.compress((b'\\0'+bytes([30,40,50])*w)*h))+chunk(b'IEND',b''))
Path('out').mkdir()
Path('out/0.png').write_bytes(png(768,1152))
Path('out/thumb-0.png').write_bytes(png(128,192))
print(json.dumps({'event':'progress','done':1}),flush=True)
print(json.dumps({'event':'result','images':[{'index':0,'seed':r['seeds'][0],'box':None}],'prompt_tokens':20,'runtime':{'torch':'fixture'}}),flush=True)
"""


def png(width, height):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + bytes([20, 30, 40]) * width) * height))
        + chunk(b"IEND", b"")
    )


def request():
    return PoseGenerationRequest(
        prompt="same character sitting",
        negative_prompt="",
        width=768,
        height=1152,
        steps=4,
        guidance=1,
        seeds=(19,),
        reference=png(80, 120),
    )


def generator(tmp_path, code=FAKE, deadline=5):
    script = tmp_path / "child.py"
    script.write_text(code, encoding="utf-8")
    return LocalPoseGenerator(
        python=Path(sys.executable),
        script=script,
        model_dir=tmp_path,
        model=ModelIdentity(MODEL_REPO, MODEL_REVISION, "apache-2.0"),
        model_manifest_sha256="a" * 64,
        cutout_manifest_sha256=None,
        deadline_seconds=deadline,
    )


async def test_child_result_is_verified_and_progress_is_forwarded(tmp_path):
    progress = []

    async def update(done):
        progress.append(done)

    result = await generator(tmp_path).generate(request(), on_progress=update)
    assert result.images[0].seed == 19
    assert (result.images[0].width, result.images[0].height) == (768, 1152)
    assert result.prompt_tokens == 20 and result.truncated is False
    assert 1 in progress


async def test_wrong_seed_is_rejected_instead_of_published(tmp_path):
    async def update(_done):
        pass

    child = generator(tmp_path, FAKE.replace("r['seeds'][0]", "r['seeds'][0]+1"))
    with pytest.raises(ImageGenerationError, match="invalid_output"):
        await child.generate(request(), on_progress=update)


async def test_stalled_child_has_a_deadline(tmp_path):
    async def update(_done):
        pass

    child = generator(tmp_path, "import time;time.sleep(30)", deadline=0.2)
    with pytest.raises(ImageGenerationError, match="generation_timeout"):
        await child.generate(request(), on_progress=update)


async def test_model_cache_is_private_without_inheriting_operator_identity(tmp_path):
    async def update(_done):
        pass

    code = FAKE.replace(
        "r=json.load(sys.stdin)",
        "import os\n"
        "assert os.environ['TORCHINDUCTOR_CACHE_DIR'].startswith(os.environ['TEMP'])\n"
        "assert 'FLINT_GRAPH_DATABASE_URL' not in os.environ\nr=json.load(sys.stdin)",
    )
    result = await generator(tmp_path, code).generate(request(), on_progress=update)
    assert len(result.images) == 1


async def test_deadline_also_stops_descendants_of_the_owned_child(tmp_path):
    import asyncio

    marker = tmp_path / "escaped.txt"
    grandchild = f"import time;time.sleep(1);open({str(marker)!r},'w').write('escaped')"
    code = (
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable,'-c',{grandchild!r}])\n"
        "time.sleep(30)"
    )

    async def update(_done):
        pass

    with pytest.raises(ImageGenerationError, match="generation_timeout"):
        await generator(tmp_path, code, deadline=0.35).generate(request(), on_progress=update)
    await asyncio.sleep(1.1)
    assert not marker.exists(), "A cancelled model child left its descendant running"


async def test_additional_view_is_transferred_with_ordered_hashes_and_private_files(tmp_path):
    from dataclasses import replace

    code = FAKE.replace(
        "r=json.load(sys.stdin)",
        "r=json.load(sys.stdin)\nassert r['schema_version']==2\n"
        "assert len(r['reference_sha256s'])==2\n"
        "assert Path('reference-0.png').is_file()\nassert Path('reference-1.png').is_file()",
    )

    async def update(_done):
        pass

    result = await generator(tmp_path, code).generate(
        replace(request(), additional_references=(png(96, 128),)), on_progress=update
    )
    assert len(result.images) == 1


async def test_both_adapters_transfer_as_verified_private_files_in_character_then_style_order(
    tmp_path,
):
    from dataclasses import replace

    from test_narrative_style_weights import weights

    from flint_graph.infrastructure.narrative_posegen import PoseStyleAdapter

    code = FAKE.replace(
        "r=json.load(sys.stdin)",
        "r=json.load(sys.stdin)\nimport hashlib\nassert r['schema_version']==4\n"
        "assert [a['role'] for a in r['adapters']]==['character','style']\n"
        "assert [a['strength'] for a in r['adapters']]==[0.6,0.4]\n"
        "for a in r['adapters']:\n"
        " data=Path(a['role']+'.safetensors').read_bytes()\n"
        " assert hashlib.sha256(data).hexdigest()==a['sha256']\n"
        "assert 'style' not in r\nassert Path('reference.png').is_file()",
    )
    blob = weights().replace(b"b" * 64, b"a" * 64)
    character = PoseStyleAdapter(blob, "c" * 64, "d" * 64, 0.6)
    style = PoseStyleAdapter(blob.replace(b"c" * 64, b"e" * 64), "e" * 64, "d" * 64, 0.4)

    async def update(_done):
        pass

    result = await generator(tmp_path, code).generate(
        replace(request(), character_adapter=character, style_adapter=style), on_progress=update
    )
    assert len(result.images) == 1
    with pytest.raises(ImageGenerationError, match="bad_request"):
        await generator(tmp_path).generate(
            replace(
                request(), character_adapter=character, style_adapter=replace(style, strength=0.6)
            ),
            on_progress=update,
        )


@pytest.mark.parametrize("corrupt", [False, True])
async def test_repair_parent_rejects_a_child_that_changes_any_outside_pixel(tmp_path, corrupt):
    from dataclasses import replace

    from flint_graph.infrastructure.narrative_posegen import PoseRepairRegion

    source = png(768, 1152)
    patch = """
assert r['schema_version']==5 and r['repair']['box']==[400,500,560,660]
assert r['adapters']==[]
data=Path('reference-0.png').read_bytes()
raw=bytearray(zlib.decompress(data[41:-16]))
for y in range(500,660):
 start=y*(768*3+1)+1+400*3
 raw[start:start+160*3]=bytes([90,80,70])*160
CORRUPT
def chunk(k,p):return struct.pack('>I',len(p))+k+p+struct.pack('>I',zlib.crc32(k+p))
Path('out/0.png').write_bytes(data[:33]+chunk(b'IDAT',zlib.compress(raw))+data[-12:])
""".replace("CORRUPT", "raw[1]=99" if corrupt else "")
    code = FAKE.replace("Path('out/0.png').write_bytes(png(768,1152))", patch)

    async def update(_done):
        pass

    pending = replace(
        request(),
        reference=source,
        additional_references=(png(80, 120),),
        repair=PoseRepairRegion((400, 500, 560, 660), None, 768, 1152),
    )
    if corrupt:
        with pytest.raises(ImageGenerationError, match="repair_preservation_failed"):
            await generator(tmp_path, code).generate(pending, on_progress=update)
    else:
        result = await generator(tmp_path, code).generate(pending, on_progress=update)
        assert len(result.images) == 1 and result.images[0].data != source
        assert len(result.runtime["repair_preserved_sha256"]) == 64


async def test_body_guidance_transfers_a_pinned_public_adapter_and_frozen_skeleton(tmp_path):
    from dataclasses import replace
    from hashlib import sha256

    from flint_graph.infrastructure.narrative_posegen import PoseControlModel, PoseGuideCondition
    from flint_graph.narrative.pose_guides import body_guide, guide_sha256

    guide = body_guide("seated-front-v1")
    path = tmp_path / "pose.safetensors"
    path.write_bytes(b"verified test weights")
    model = PoseControlModel(
        path, sha256(path.read_bytes()).hexdigest(), path.stat().st_size, "c" * 64
    )
    code = FAKE.replace(
        "r=json.load(sys.stdin)",
        "r=json.load(sys.stdin)\nimport hashlib\nassert r['schema_version']==6\nassert r['control']['guide']['points'][10]!=r['control']['guide']['points'][13]\nassert hashlib.sha256(Path('pose-control.safetensors').read_bytes()).hexdigest()==r['control']['weights_sha256']\nassert r['reference_sha256s'] and len(r['reference_sha256s'])==1",  # noqa: E501
    )
    engine = generator(tmp_path, code)
    engine.control_model = model
    condition = PoseGuideCondition(guide, guide_sha256(guide), "c" * 64)

    async def update(_done):
        pass

    result = await engine.generate(replace(request(), pose_guide=condition), on_progress=update)
    assert len(result.images) == 1
    path.write_bytes(b"changed test weights")
    with pytest.raises(ImageGenerationError, match="pose_control_unavailable"):
        await engine.generate(replace(request(), pose_guide=condition), on_progress=update)


def test_control_model_manifest_requires_an_object_before_loading_weights(tmp_path):
    from hashlib import sha256

    from flint_graph.infrastructure.narrative_posegen import verify_control_model

    manifest = tmp_path / "flintgraph-download.json"
    manifest.write_bytes(b"[]")
    with pytest.raises(ValueError, match="pose_control_unavailable"):
        verify_control_model(tmp_path, sha256(manifest.read_bytes()).hexdigest())
