"""Resolve the implemented vector templates; never invent external assets."""
from __future__ import annotations
from ..schemas import Storyboard
from .contracts import AssetManifest

AVAILABLE_TEMPLATES = {"KineticTypography", "EducationalExplainer"}


class AssetAgent:
    def run(self, storyboard: Storyboard) -> AssetManifest:
        used = {scene.template for scene in storyboard.scenes}
        unavailable = used - AVAILABLE_TEMPLATES
        if unavailable:
            raise ValueError(f"templates not implemented: {', '.join(sorted(unavailable))}")
        if any(scene.assetRefs or scene.audio for scene in storyboard.scenes):
            raise ValueError("external scene assets/audio require an approved local asset manifest")
        if storyboard.backgroundMusic:
            raise ValueError("background music requires a licensed local asset manifest")
        return AssetManifest(templates=sorted(used))
