import json

import pytest

from packages.core.config import PROJECT_ROOT
from packages.core.media.process import sha256_file
from packages.core.schemas import Storyboard, VideoMetadata


def thumbnail_inputs():
    fixture = json.loads((PROJECT_ROOT / "packages/video/fixtures/all-templates.json").read_text(encoding="utf-8"))
    return Storyboard.model_validate(fixture), VideoMetadata(
        title="Cerita bergerak dari ide", description="Demonstrasi lokal, konten fiksi.",
        thumbnail={"text": "SATU IDE", "layout": "operator concept", "background": "theme"})


def test_thumbnail_is_real_deterministic_vertical_png(tmp_path):
    from packages.core.media.thumbnail import ThumbnailAgent, verify_thumbnail
    storyboard, metadata = thumbnail_inputs()
    first = ThumbnailAgent().run(storyboard, metadata, tmp_path)
    path = tmp_path / first.output_path
    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert (first.width, first.height) == (1080, 1920)
    assert first.sha256 == sha256_file(path)
    verify_thumbnail(first, storyboard, metadata, tmp_path)
    second = ThumbnailAgent().run(storyboard, metadata, tmp_path)
    assert second.sha256 == first.sha256
    with path.open("ab") as stream:
        stream.write(b"mutation")
    with pytest.raises(ValueError, match="checksum"):
        verify_thumbnail(second, storyboard, metadata, tmp_path)


def test_thumbnail_rejects_metadata_mutation(tmp_path):
    from packages.core.media.thumbnail import ThumbnailAgent, verify_thumbnail
    storyboard, metadata = thumbnail_inputs()
    thumbnail = ThumbnailAgent().run(storyboard, metadata, tmp_path)
    metadata.thumbnail["text"] = "BARU"
    with pytest.raises(ValueError, match="metadata"):
        verify_thumbnail(thumbnail, storyboard, metadata, tmp_path)


def test_thumbnail_regenerates_when_metadata_changes_on_resume(tmp_path):
    from packages.core.media.thumbnail import ThumbnailAgent, verify_thumbnail
    from packages.core.media.process import atomic_json

    storyboard, metadata = thumbnail_inputs()
    agent = ThumbnailAgent()
    original = agent.run(storyboard, metadata, tmp_path)
    atomic_json(tmp_path / "thumbnail.json", original.model_dump(mode="json"))
    metadata.thumbnail["text"] = "BARU"

    revised = agent.run(storyboard, metadata, tmp_path)

    assert revised.metadata_sha256 != original.metadata_sha256
    verify_thumbnail(revised, storyboard, metadata, tmp_path)
