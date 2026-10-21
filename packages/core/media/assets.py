"""Resolve explicitly licensed local files; no downloads or invented attribution."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..schemas import ALLOWED_TEMPLATES, Storyboard
from .contracts import AssetManifest, LocalAssetLibrary, ResolvedAsset
from .process import checked_path, json_hash, probe_media, sha256_file

AVAILABLE_TEMPLATES = frozenset(ALLOWED_TEMPLATES)
_IMAGE_CODECS = {".png": "png", ".jpg": "mjpeg", ".jpeg": "mjpeg", ".webp": "webp"}
_AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


def asset_dependencies(storyboard: Storyboard) -> dict:
    return {
        "scenes": [{"id": s.sceneId, "template": s.template, "assetRefs": s.assetRefs,
                    "data": s.data, "audio": s.audio} for s in storyboard.scenes],
        "backgroundMusic": storyboard.backgroundMusic,
    }


def referenced_assets(storyboard: Storyboard) -> dict[str, str]:
    refs: dict[str, str] = {}

    def add(ref, kind):
        if not isinstance(ref, str) or not ref:
            raise ValueError("assetRef must be a nonempty local manifest id")
        if ref in refs and refs[ref] != kind:
            raise ValueError("asset cannot be used with conflicting media kinds")
        refs[ref] = kind

    for scene in storyboard.scenes:
        for ref in scene.assetRefs:
            add(ref, "image")
        for collection in ("panels", "layers"):
            for entry in (scene.data or {}).get(collection, []):
                if entry.get("assetRef"):
                    if entry["assetRef"] not in scene.assetRefs:
                        raise ValueError("template image assetRef must also appear in scene.assetRefs")
                    add(entry["assetRef"], "image")
        if scene.audio:
            from .scene_data import SceneAudioSpec
            effects = SceneAudioSpec.model_validate(scene.audio)
            for effect in effects.sfx:
                add(effect.assetRef, "sfx")
    if storyboard.backgroundMusic:
        from .scene_data import BackgroundMusicSpec
        music = BackgroundMusicSpec.model_validate(storyboard.backgroundMusic)
        add(music.assetRef, "music")
    return refs


def _validate_templates(storyboard: Storyboard) -> None:
    from .scene_data import validate_scene_data
    for scene in storyboard.scenes:
        if scene.template not in AVAILABLE_TEMPLATES:
            raise ValueError(f"template not implemented: {scene.template}")
        validate_scene_data(scene.template, scene.data)


def _verify_source(root: Path, asset) -> Path:
    path = checked_path(root, asset.path)
    if not path.is_file() or sha256_file(path) != asset.sha256:
        raise ValueError(f"asset {asset.id}: missing file or checksum mismatch")
    if asset.license_file:
        license_path = checked_path(root, asset.license_file)
        if not license_path.is_file() or sha256_file(license_path) != asset.license_sha256:
            raise ValueError(f"asset {asset.id}: license checksum mismatch")
    suffix = path.suffix.lower()
    if asset.kind == "image" and suffix not in _IMAGE_CODECS:
        raise ValueError("only local raster PNG/JPEG/WebP image assets are supported")
    if asset.kind != "image" and suffix not in _AUDIO_SUFFIXES:
        raise ValueError("unsupported local audio asset format")
    streams = probe_media(path).get("streams", [])
    if asset.kind == "image":
        images = [s for s in streams if s.get("codec_type") == "video"]
        if len(images) != 1 or images[0].get("codec_name") != _IMAGE_CODECS[suffix]:
            raise ValueError("asset is not the declared raster image type")
    elif len([s for s in streams if s.get("codec_type") == "audio"]) != 1 or any(
        s.get("codec_type") == "video" for s in streams
    ):
        raise ValueError("audio asset requires exactly one audio stream and no video")
    return path


class AssetAgent:
    def run(self, storyboard: Storyboard, job_dir: Path | None = None,
            *, manifest_path: Path | None = None) -> AssetManifest:
        _validate_templates(storyboard)
        used = sorted({scene.template for scene in storyboard.scenes})
        refs = referenced_assets(storyboard)
        dependency_hash = json_hash(asset_dependencies(storyboard))
        if not refs:
            return AssetManifest(templates=used, dependencies_sha256=dependency_hash)
        if job_dir is None:
            raise ValueError("local assets require a job directory and approved local manifest")
        manifest_path = Path(manifest_path) if manifest_path else job_dir / "assets-manifest.json"
        root = manifest_path.absolute().parent
        manifest_file = checked_path(root, manifest_path.name)
        if not manifest_file.is_file():
            raise ValueError("licensed local assets require an explicit local assets-manifest.json")
        manifest_hash = sha256_file(manifest_file)
        library = LocalAssetLibrary.model_validate_json(manifest_file.read_text(encoding="utf-8"))
        by_id = {asset.id: asset for asset in library.assets}
        if missing := refs.keys() - by_id.keys():
            raise ValueError("unresolved asset refs: " + ", ".join(sorted(missing)))
        resolved = []
        for ref, kind in sorted(refs.items()):
            asset = by_id[ref]
            if kind != asset.kind:
                raise ValueError(f"asset {ref}: expected {kind}, manifest declares {asset.kind}")
            original = _verify_source(root, asset)
            relative = f"assets/{asset.sha256}{original.suffix.lower()}"
            staged = checked_path(job_dir, relative)
            staged.parent.mkdir(parents=True, exist_ok=True)
            if staged.exists() and sha256_file(staged) != asset.sha256:
                raise ValueError("staged asset checksum mismatch; refusing to overwrite mutation")
            if not staged.exists():
                shutil.copyfile(original, staged)
            if sha256_file(staged) != asset.sha256:
                raise ValueError("staged asset checksum mismatch")
            resolved.append(ResolvedAsset(**asset.model_dump(), staged_path=relative))
        if sha256_file(manifest_file) != manifest_hash:
            raise ValueError("source manifest changed during asset resolution")
        result = AssetManifest(mode="licensed-local", templates=used, assets=resolved, license="per-asset",
                               library_root=str(root), manifest_path=manifest_file.name,
                               manifest_sha256=manifest_hash, dependencies_sha256=dependency_hash)
        verify_assets(result, storyboard, job_dir)
        return result


def verify_assets(manifest: AssetManifest, storyboard: Storyboard, job_dir: Path) -> None:
    _validate_templates(storyboard)
    refs = referenced_assets(storyboard)
    if manifest.templates != sorted({scene.template for scene in storyboard.scenes}):
        raise ValueError("asset manifest templates no longer match storyboard")
    if manifest.dependencies_sha256 and manifest.dependencies_sha256 != json_hash(asset_dependencies(storyboard)):
        raise ValueError("asset dependencies no longer match storyboard")
    if not refs and manifest.mode == "project-generated-vectors":
        return
    if manifest.mode != "licensed-local" or {a.id for a in manifest.assets} != set(refs):
        raise ValueError("asset manifest does not resolve all storyboard references")
    root = Path(manifest.library_root)
    source = checked_path(root, manifest.manifest_path)
    if not source.is_file() or sha256_file(source) != manifest.manifest_sha256:
        raise ValueError("source manifest checksum mismatch")
    library = LocalAssetLibrary.model_validate_json(source.read_text(encoding="utf-8"))
    by_id = {a.id: a for a in library.assets}
    for asset in manifest.assets:
        if asset.id not in by_id or by_id[asset.id].model_dump() != asset.model_dump(exclude={"staged_path"}):
            raise ValueError("resolved asset provenance no longer matches source manifest")
        if refs[asset.id] != asset.kind:
            raise ValueError("resolved asset has incorrect media kind")
        _verify_source(root, asset)
        staged = checked_path(job_dir, asset.staged_path)
        if not staged.is_file() or sha256_file(staged) != asset.sha256:
            raise ValueError("staged asset checksum mismatch")


def load_assets(storyboard: Storyboard, job_dir: Path, assets: AssetManifest | None = None) -> AssetManifest:
    if assets is None:
        path = job_dir / "assets.json"
        assets = AssetManifest.model_validate(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else AssetAgent().run(storyboard, job_dir)
    verify_assets(assets, storyboard, job_dir)
    return assets


def render_storyboard(storyboard: Storyboard, manifest: AssetManifest) -> dict:
    """Resolve logical image ids only in renderer props, never in canonical JSON."""
    props = storyboard.model_dump(mode="json", exclude_none=True)
    paths = {asset.id: asset.staged_path for asset in manifest.assets if asset.kind == "image"}
    for scene in props["scenes"]:
        scene["assetRefs"] = [paths[ref] for ref in scene["assetRefs"]]
        for key in ("panels", "layers"):
            for item in (scene.get("data") or {}).get(key, []):
                if item.get("assetRef"):
                    item["assetRef"] = paths[item["assetRef"]]
    return props
