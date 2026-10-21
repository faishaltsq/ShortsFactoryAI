import pytest

from packages.core.schemas import SceneSpec, Storyboard
from packages.core.media.assets import referenced_assets, render_storyboard
from packages.core.media.contracts import AssetManifest, ResolvedAsset


def _scene(**data):
    return SceneSpec(
        sceneId="s1",
        template="IllustratedStory",
        segment="Cahaya butuh delapan menit untuk sampai ke Bumi.",
        durationInFrames=300,
        data=data,
    )


def test_minimal_illustration_needs_only_a_setting():
    scene = _scene(setting="space")
    assert scene.data["setting"] == "space"


def test_unknown_setting_is_rejected():
    with pytest.raises(ValueError, match="setting"):
        _scene(setting="underwater")


def test_unknown_illustration_key_is_rejected():
    with pytest.raises(ValueError):
        _scene(setting="space", camera="pushIn")


def test_actor_bounds_are_enforced():
    with pytest.raises(ValueError):
        _scene(setting="space", actors=[{"pose": "point", "x": 1.4, "ground": 0.7}])


def test_shots_are_optional():
    # validate_scene_data only validates; it does not inject defaults into scene.data.
    # The default shot is injected by normalize_illustration (tested in test_storyboard_normalize.py)
    # and by validateIllustrationData on the TypeScript side.
    assert _scene(setting="desert").data == {"setting": "desert"}


SHA = "c" * 64


def _storyboard_with_plate():
    return Storyboard(id="plate", scenes=[_scene(
        setting="ocean",
        imageRef="plate",
    ).model_copy(update={"assetRefs": ["plate"]})])


def _manifest():
    return AssetManifest(
        mode="licensed-local",
        templates=["IllustratedStory"],
        license="per-asset",
        library_root="C:/library",
        manifest_path="assets-manifest.json",
        manifest_sha256="a" * 64,
        dependencies_sha256="b" * 64,
        assets=[ResolvedAsset(
            id="plate", path="plate.png", kind="image", license="project-original",
            attribution="Operator supplied", source="local", sha256=SHA,
            staged_path=f"assets/{SHA}.png",
        )],
    )


def test_image_ref_must_be_declared_in_asset_refs():
    board = Storyboard(id="x", scenes=[_scene(setting="ocean", imageRef="plate")])
    with pytest.raises(ValueError, match="imageRef"):
        referenced_assets(board)


def test_render_props_rewrite_image_ref_to_staged_path():
    props = render_storyboard(_storyboard_with_plate(), _manifest())
    assert props["scenes"][0]["data"]["imageRef"] == f"assets/{SHA}.png"

