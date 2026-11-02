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
