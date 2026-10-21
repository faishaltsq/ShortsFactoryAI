"""Only project-created fixture pixels; no external or asserted third-party license."""
import hashlib
import json
import struct
import zlib

import pytest

from packages.core.media.assets import AssetAgent
from packages.core.schemas import SceneSpec, Storyboard


def fixture_png(path):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress((b"\0" + b"\x20\x70\x90" * 8) * 8)) + chunk(b"IEND", b""))


def licensed_fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    image = root / "project-created.png"
    fixture_png(image)
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"assets": [{
        "id": "local-panel", "path": image.name, "kind": "image",
        "license": "project-original", "attribution": "Shorts Factory AI automated test fixture",
        "source": "project:tests/test_licensed_assets.py", "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
    }]}), encoding="utf-8")
    return manifest


def image_storyboard():
    return Storyboard(id="local-media", scenes=[SceneSpec(
        sceneId="comic", template="MotionComic", segment="Ilustrasi fiksi uji.", durationInFrames=90,
        assetRefs=["local-panel"], data={"panels": [{"caption": "Ilustrasi uji", "assetRef": "local-panel"}]},
    )])


def test_resolve_licensed_local_image_preserves_original_and_stages_verified_file(tmp_path):
    manifest_path = licensed_fixture(tmp_path / "library")
    job = tmp_path / "job"
    job.mkdir()
    manifest = AssetAgent().run(image_storyboard(), job, manifest_path=manifest_path)
    item = manifest.assets[0]
    assert item.id == "local-panel"
    assert item.license == "project-original"
    assert item.attribution == "Shorts Factory AI automated test fixture"
    assert item.source == "project:tests/test_licensed_assets.py"
    assert item.sha256 == hashlib.sha256((job / item.staged_path).read_bytes()).hexdigest()
    assert (manifest_path.parent / item.path).is_file()
    assert manifest.manifest_sha256 == hashlib.sha256(manifest_path.read_bytes()).hexdigest()


@pytest.mark.parametrize("template,data", [
    ("MotionComic", {"panels": [{"caption": "Panel asli"}]}),
    ("HistoricalTimeline", {"events": [{"date": "1900", "label": "Awal"}, {"date": "1901", "label": "Lanjutan"}]}),
    ("ParallaxStory", {"title": "Kisah", "layers": [{"shape": "ridge", "depth": 0.3}]}),
    ("InfographicMotion", {"title": "Data uji", "items": [{"label": "Satu", "value": 10}]}),
])
def test_named_template_data_is_validated_without_fallback(template, data):
    storyboard = Storyboard(id="vectors", scenes=[SceneSpec(sceneId="a", template=template, segment="Fiksi uji", data=data)])
    assert AssetAgent().run(storyboard).templates == [template]
    storyboard.scenes[0].data = {}
    with pytest.raises(ValueError):
        AssetAgent().run(storyboard)


@pytest.mark.parametrize("change", [
    {"path": "../outside.png"}, {"path": "https://example.com/image.png"},
    {"license": "unknown license"}, {"attribution": ""}, {"sha256": "0" * 64},
])
def test_manifest_rejects_unconfined_or_unverifiable_assets(tmp_path, change):
    manifest_path = licensed_fixture(tmp_path / "library")
    data = json.loads(manifest_path.read_text())
    data["assets"][0].update(change)
    manifest_path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        AssetAgent().run(image_storyboard(), tmp_path, manifest_path=manifest_path)


@pytest.mark.parametrize("target", ["source", "manifest", "staged"])
def test_asset_resume_rejects_mutated_bytes(tmp_path, target):
    from packages.core.media.assets import verify_assets
    manifest_path = licensed_fixture(tmp_path / "library")
    job = tmp_path / "job"
    job.mkdir()
    storyboard = image_storyboard()
    manifest = AssetAgent().run(storyboard, job, manifest_path=manifest_path)
    paths = {"source": manifest_path.parent / manifest.assets[0].path,
             "manifest": manifest_path, "staged": job / manifest.assets[0].staged_path}
    with paths[target].open("ab") as stream:
        stream.write(b"mutation")
    with pytest.raises(ValueError, match="checksum"):
        verify_assets(manifest, storyboard, job)


def test_asset_path_rejects_symlink_escape(tmp_path):
    manifest_path = licensed_fixture(tmp_path / "library")
    outside = tmp_path / "outside.png"
    fixture_png(outside)
    linked = manifest_path.parent / "escape.png"
    try:
        linked.symlink_to(outside)
    except OSError:
        pytest.skip("Windows symlink privilege is unavailable")
    data = json.loads(manifest_path.read_text())
    data["assets"][0]["path"] = linked.name
    manifest_path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="escaped"):
        AssetAgent().run(image_storyboard(), tmp_path, manifest_path=manifest_path)


def test_resolved_props_never_mutate_canonical_storyboard(tmp_path):
    from packages.core.media.assets import render_storyboard
    manifest_path = licensed_fixture(tmp_path / "library")
    storyboard = image_storyboard()
    manifest = AssetAgent().run(storyboard, tmp_path, manifest_path=manifest_path)
    props = render_storyboard(storyboard, manifest)
    assert props["scenes"][0]["data"]["panels"][0]["assetRef"] == manifest.assets[0].staged_path
    assert storyboard.scenes[0].data["panels"][0]["assetRef"] == "local-panel"


def test_scene_contract_rejects_present_incomplete_template_data():
    with pytest.raises(ValueError):
        SceneSpec(sceneId="broken", template="HistoricalTimeline", segment="Uji", data={"events": []})


def test_pipeline_resolves_job_local_licensed_image(tmp_path):
    from packages.core.config import get_settings
    from packages.core.orchestration import JobStore
    from packages.core.pipeline import PipelineRunner

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="licensed storyboard")
    job_dir = store.artifact_root(job.id)
    licensed_fixture(job_dir).rename(job_dir / "assets-manifest.json")
    store.write_artifact(job.id, "storyboard.json", image_storyboard().model_dump(mode="json"))

    PipelineRunner(store, get_settings(), force_mock=True)._assets(job.id)

    result = store.read_artifact(job.id, "assets.json")
    assert result["mode"] == "licensed-local"
    assert (job_dir / result["assets"][0]["staged_path"]).is_file()
