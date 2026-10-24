import pytest
from pydantic import ValidationError

from packages.core.schemas import (
    SceneSpec,
    Script,
    ScriptSegment,
    Storyboard,
    SubtitleCue,
)


def _scene(scene_id="s1", start=0, dur=300, template="KineticTypography"):
    return SceneSpec(
        sceneId=scene_id,
        template=template,
        segment="teks naratif",
        text=[{"id": "t1", "text": "Judul", "style": {"role": "title"}}],
        startFrame=start,
        durationInFrames=dur,
    )


def test_unknown_template_rejected():
    with pytest.raises(ValidationError):
        _scene(template="RandomTemplate")


def test_storyboard_rejects_gap():
    with pytest.raises(ValidationError):
        Storyboard(id="x", scenes=[_scene("s1", 0, 300), _scene("s2", 400, 300)])


def test_storyboard_accepts_contiguous():
    sb = Storyboard(id="x", scenes=[_scene("s1", 0, 300), _scene("s2", 300, 300)])
    assert sb.total_frames == 600


def test_script_requires_hook():
    with pytest.raises(ValidationError):
        Script(
            title="t",
            genre="science",
            segments=[ScriptSegment(kind="body", text="hanya body")],
        )


def test_subtitle_ordering():
    with pytest.raises(ValidationError):
        SubtitleCue(id="s", text="x", startMs=1000, endMs=1000)


def test_storyboard_rejects_music_that_names_no_asset():
    """The contract must fail where the block is written, not three stages later."""
    with pytest.raises(ValidationError):
        Storyboard(id="x", backgroundMusic={"mood": "curious", "intensity": 0.35},
                   scenes=[_scene("s1", 0, 300)])


def test_storyboard_accepts_a_licensed_music_reference():
    sb = Storyboard(id="x", backgroundMusic={"assetRef": "bgm-01", "volume": 0.2},
                    scenes=[_scene("s1", 0, 300)])
    assert sb.backgroundMusic == {"assetRef": "bgm-01", "volume": 0.2}
