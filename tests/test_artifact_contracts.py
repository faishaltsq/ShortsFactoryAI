"""Kontrak artifact harus tahan terhadap field tambahan dari model.

Model live sering menambahkan catatan sendiri di luar skema yang diminta.
Menolak seluruh artifact karena satu field ekstra membuang hasil QC yang
sebenarnya sudah benar — dan itu menggagalkan job di tengah pipeline.
"""
import json

import pytest

from packages.core.artifacts import DraftQualityArtifact


def _sample(**extra_technical) -> dict:
    return {
        "technical": {"pass": False, "findings": ["durasi 51s > 45s"], **extra_technical},
        "editorial": {"pass": False, "findings": ["s2 dan s3 redundan"]},
        "factual": {"pass": True, "unsupported_claims": [], "findings": ["sumber Wikipedia"]},
        "overall": "fail",
    }


def test_field_ekstra_di_section_diabaikan():
    model = DraftQualityArtifact.model_validate(_sample(narration_null_subtitle_unverifiable=True))
    assert model.overall == "fail"
    assert model.technical.passed is False
    assert model.technical.findings == ["durasi 51s > 45s"]


def test_findings_di_factual_diterima():
    """Model menambahkan findings pada factual; itu catatan berguna, bukan error."""
    model = DraftQualityArtifact.model_validate(_sample())
    assert model.factual.findings == ["sumber Wikipedia"]
    assert model.factual.passed is True


def test_alias_pass_dipakai():
    model = DraftQualityArtifact.model_validate(_sample())
    assert model.technical.passed is False, "alias 'pass' harus terbaca sebagai passed"


def test_overall_tetap_divalidasi():
    bad = _sample()
    bad["overall"] = "maybe"
    with pytest.raises(Exception):
        DraftQualityArtifact.model_validate(bad)


def test_artifact_tersimpan_bisa_dibaca_ulang(tmp_path):
    """Round-trip: yang ditulis ke disk harus lolos validasi saat dibaca."""
    model = DraftQualityArtifact.model_validate(_sample(extra_note="catatan"))
    path = tmp_path / "draft_qc.json"
    path.write_text(json.dumps(model.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    again = DraftQualityArtifact.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert again.overall == model.overall
