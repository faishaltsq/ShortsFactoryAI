"""Deterministic local Remotion PNG thumbnail with content-bound provenance."""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Callable

from ..config import PROJECT_ROOT
from ..schemas import Storyboard, VideoMetadata
from .assets import load_assets, render_storyboard
from .contracts import AssetManifest, ThumbnailArtifact
from .process import atomic_json, checked_path, json_hash, probe_media, run_checked, sha256_file


def _metadata(metadata: VideoMetadata | dict) -> dict:
    return metadata.model_dump(mode="json", exclude_none=True) if isinstance(metadata, VideoMetadata) else dict(metadata)


def verify_thumbnail(artifact: ThumbnailArtifact, storyboard: Storyboard, metadata: VideoMetadata | dict,
                     job_dir: Path, *, assets: AssetManifest | None = None) -> None:
    if artifact.storyboard_sha256 != json_hash(storyboard.model_dump(mode="json", exclude_none=True)):
        raise ValueError("thumbnail no longer matches storyboard")
    if artifact.metadata_sha256 != json_hash(_metadata(metadata)):
        raise ValueError("thumbnail no longer matches metadata")
    resolved = load_assets(storyboard, job_dir, assets)
    if artifact.assets_sha256 != json_hash(resolved.model_dump(mode="json")):
        raise ValueError("thumbnail asset manifest checksum mismatch")
    scene = next((s for s in storyboard.scenes if s.sceneId == artifact.scene_id), None)
    if scene is None or artifact.frame >= scene.durationInFrames:
        raise ValueError("thumbnail frame does not belong to selected scene")
    path = checked_path(job_dir, artifact.output_path)
    if not path.is_file() or sha256_file(path) != artifact.sha256:
        raise ValueError("thumbnail checksum mismatch")
    with path.open("rb") as source:
        header = source.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", header[16:24]) != (1080, 1920):
        raise ValueError("thumbnail must be a real 1080x1920 PNG")
    streams = probe_media(path).get("streams", [])
    if len(streams) != 1 or streams[0].get("codec_name") != "png" or (streams[0].get("width"), streams[0].get("height")) != (1080, 1920):
        raise ValueError("thumbnail could not be decoded as vertical PNG")


class ThumbnailAgent:
    def __init__(self, video_dir: Path | None = None) -> None:
        self.video_dir = video_dir or PROJECT_ROOT / "packages/video"

    def run(self, storyboard: Storyboard, metadata: VideoMetadata | dict, job_dir: Path,
            cancelled: Callable[[], bool] | None = None, *, assets: AssetManifest | None = None) -> ThumbnailArtifact:
        if (storyboard.width, storyboard.height) != (1080, 1920):
            raise ValueError("thumbnail supports the vertical 1080x1920 profile only")
        resolved = load_assets(storyboard, job_dir, assets)
        meta = _metadata(metadata)
        headline = meta.get("thumbnail", {}).get("text")
        if not isinstance(headline, str) or not 1 <= len(headline.strip()) <= 32:
            raise ValueError("thumbnail metadata.text must contain 1-32 characters")
        cached_path = job_dir / "thumbnail.json"
        if cached_path.is_file():
            cached = ThumbnailArtifact.model_validate_json(cached_path.read_text(encoding="utf-8"))
            if (cached.storyboard_sha256 == json_hash(storyboard.model_dump(mode="json", exclude_none=True))
                    and cached.metadata_sha256 == json_hash(meta)
                    and cached.assets_sha256 == json_hash(resolved.model_dump(mode="json"))):
                verify_thumbnail(cached, storyboard, metadata, job_dir, assets=resolved)
                return cached
        cli = self.video_dir / "node_modules/@remotion/cli/remotion-cli.js"
        if not cli.is_file():
            raise ValueError("Remotion dependencies are not installed")
        props = render_storyboard(storyboard, resolved)
        scene = props["scenes"][0]
        frame = min(scene["durationInFrames"] - 1, max(1, round(scene["durationInFrames"] * 0.7)))
        props_path = checked_path(job_dir, "thumbnail-props.json")
        atomic_json(props_path, {"scene": scene, "theme": props["theme"], "headline": headline.strip(),
                                 "watermark": props.get("watermark", {}).get("text")})
        partial = checked_path(job_dir, "thumbnail.partial.png")
        run_checked(["node", str(cli), "still", "src/index.ts", "Thumbnail", str(partial),
                     "--props=" + str(props_path), "--frame=" + str(frame), "--public-dir=" + str(job_dir),
                     "--overwrite", "--log=error"], cwd=self.video_dir, log_path=job_dir / "thumbnail.log",
                    timeout=120, cancelled=cancelled)
        output = checked_path(job_dir, "thumbnail.png")
        partial.replace(output)
        artifact = ThumbnailArtifact(output_path="thumbnail.png", sha256=sha256_file(output),
                                     storyboard_sha256=json_hash(storyboard.model_dump(mode="json", exclude_none=True)),
                                     metadata_sha256=json_hash(meta), assets_sha256=json_hash(resolved.model_dump(mode="json")),
                                     scene_id=scene["sceneId"], frame=frame)
        verify_thumbnail(artifact, storyboard, metadata, job_dir, assets=resolved)
        return artifact
