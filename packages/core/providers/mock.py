"""Deterministic in-process provider. Default for tests and for unverified live access.

Fixtures are keyed by task name. Each fixture is a JSON string so agent parsing
code is exercised exactly as with a live model.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from .base import ProviderResult, Tier

Fixture = Callable[[str, str, str], str]

FIXTURES: dict[str, str] = {
    "research": json.dumps(
        {
            "candidates": [
                {
                    "topic_id": "t-sunlight-delay",
                    "title": "Cahaya matahari butuh 8 menit untuk sampai ke bumi",
                    "genre": "science",
                    "hook": "Yang kamu lihat di langit sekarang sudah terjadi 8 menit lalu.",
                    "angle": "Fakta jarak tata suryla disampaikan sebagai perjalanan waktu pribadi.",
                    "sources": [
                        {"title": "NASA Solar System Exploration", "url": "https://science.nasa.gov/solar-system/", "publisher": "NASA", "published": "2024-06-01"}
                    ],
                    "verification": "supported",
                    "visual_potential": 8,
                    "novelty": 7,
                },
                {
                    "topic_id": "t-roman-concrete",
                    "title": "Beton Romawi lebih kuat dari beton modern karena laut",
                    "genre": "history",
                    "hook": "Rahasia beton yang bertahan 2000 tahun baru terungkap.",
                    "angle": "Reaksi air laut dengan abu vulkanik.",
                    "sources": [
                        {"title": "MIT News: Roman concrete", "url": "https://news.mit.edu/2023", "publisher": "MIT", "published": "2023-01-20"}
                    ],
                    "verification": "supported",
                    "visual_potential": 7,
                    "novelty": 6,
                },
            ]
        }
    ),
    "topic_selection": json.dumps(
        {
            "selected_topic_id": "t-sunlight-delay",
            "rationale": "Hook paling kuat, verifikasi mudah, potensi visual tinggi, genre sains melengkapi backlog.",
            "scores": {"originality": 7, "hook": 9, "verifiability": 9, "visual": 8, "genre_diversity": 8},
            "genre": "science",
        }
    ),
    "script": json.dumps(
        {
            "title": "Cahaya yang Kau Lihat Adalah Masa Lalu",
            "genre": "science",
            "content_type": "factual",
            "segments": [
                {"kind": "hook", "text": "Tahukah kau, cahaya yang kau lihat di langit sekarang sudah berangkat 8 menit lalu?"},
                {"kind": "body", "text": "Jarak matahari ke bumi 149,6 juta kilometer, dan cahaya menempuhnya dengan kecepatan 300.000 kilometer per detik."},
                {"kind": "body", "text": "Artinya setiap tatapan ke langit selalu menatap masa lalu."},
                {"kind": "payoff", "text": "Malam ini, lihat bulan. Cahayanya butuh lebih dari satu detik untuk sampai ke matamu."},
            ],
            "sources": [{"title": "NASA Solar System Exploration", "url": "https://science.nasa.gov/solar-system/", "publisher": "NASA", "published": "2024-06-01"}],
            "estimated_duration_s": 34,
        }
    ),
    "creative_review": json.dumps(
        {
            "verdict": "approve",
            "weak_spots": ["Payoff bisa lebih personal."],
            "revisions": [
                {"segment_index": 3, "replacement": "Malam ini, lihat bulan. Cahayanya butuh 1,3 detik untuk sampai ke matamu, cukup waktu untuk berkedip dua kali."}
            ],
            "notes": "Hook kuat, alur naik, ending beresonansi.",
        }
    ),
    "storyboard": json.dumps(
        {
            "storyboard": {
                "id": "sb-mock-1",
                "language": "id-ID",
                "width": 1080,
                "height": 1920,
                "fps": 30,
                "theme": {"id": "midnight"},
                "scenes": [
                    {
                        "sceneId": "scene-01",
                        "template": "KineticTypography",
                        "segment": "Tahukah kau, cahaya yang kau lihat di langit sekarang sudah berangkat 8 menit lalu?",
                        "assetRefs": [],
                        "text": [{"id": "t1", "text": "Cahaya Butuh 8 Menit", "style": {"role": "title"}}],
                        "animation": {"preset": "wordByWord", "durationInFrames": 24},
                        "transition": {"type": "fade", "durationInFrames": 10},
                        "startFrame": 0,
                        "durationInFrames": 270,
                        "data": {"highlightIndex": 3},
                    },
                    {
                        "sceneId": "scene-02",
                        "template": "EducationalExplainer",
                        "segment": "Jarak matahari ke bumi 149,6 juta kilometer.",
                        "assetRefs": [],
                        "text": [
                            {"id": "t2", "text": "Matahari ke Bumi", "style": {"role": "title"}},
                            {"id": "k2", "text": "Fakta Angkasa", "style": {"role": "kicker"}},
                        ],
                        "animation": {"preset": "slideUp", "durationInFrames": 24},
                        "transition": {"type": "slideUp", "durationInFrames": 12},
                        "startFrame": 270,
                        "durationInFrames": 330,
                        "data": {"bullets": ["149,6 juta kilometer.", "300.000 km per detik.", "8 menit 20 detik."]},
                    },
                    {
                        "sceneId": "scene-03",
                        "template": "KineticTypography",
                        "segment": "Malam ini, lihat bulan.",
                        "assetRefs": [],
                        "text": [{"id": "t3", "text": "Lihat Bulan Malam Ini", "style": {"role": "title"}}],
                        "animation": {"preset": "popIn", "durationInFrames": 24},
                        "transition": {"type": "fade", "durationInFrames": 12},
                        "startFrame": 600,
                        "durationInFrames": 300,
                        "data": {"highlightIndex": 1},
                    },
                ],
                "subtitles": [
                    {"id": "s1", "text": "Tahukah kau, cahaya di langit", "startMs": 0, "endMs": 3000},
                    {"id": "s2", "text": "sudah berangkat 8 menit lalu?", "startMs": 3000, "endMs": 6500},
                    {"id": "s3", "text": "Jaraknya 149,6 juta kilometer.", "startMs": 7000, "endMs": 11000},
                    {"id": "s4", "text": "Malam ini, lihat bulan.", "startMs": 19000, "endMs": 23000},
                ],
            }
        }
    ),
    "quality": json.dumps(
        {
            "technical": {"pass": True, "findings": []},
            "editorial": {"pass": True, "findings": ["Payoff sudah diperkuat."]},
            "factual": {"pass": True, "unsupported_claims": []},
            "overall": "pass",
        }
    ),
    "metadata": json.dumps(
        {
            "title": "Cahaya Matahari yang Kau Lihat Sudah 8 Menit Lalu #shorts",
            "description": "Fakta sains tata surya dalam 40 detik. Sumber: NASA.",
            "tags": ["sains", "tata surya", "fakta menarik", "shorts"],
            "thumbnail": {"text": "8 MENIT", "layout": "center-burst", "background": "midnight"},
        }
    ),
}


# Keep the demo visuals aligned to every script segment. Timings here are
# draft-only; AudioAgent replaces them using the actual generated narration.
_demo_script = json.loads(FIXTURES["script"])
_demo_script["segments"] = [
    {"kind": "hook", "text": "Kamu sedang melihat masa lalu setiap kali melihat cahaya Matahari. Ini bukan mesin waktu."},
    {"kind": "body", "text": "Jarak rata-rata Matahari ke Bumi sekitar 149,6 juta kilometer. Dengan kecepatan hampir 300 ribu kilometer per detik, cahaya memerlukan sekitar delapan menit dua puluh detik untuk menempuhnya."},
    {"kind": "body", "text": "Jadi, cahaya Matahari yang tiba di Bumi membawa kabar dari beberapa menit sebelumnya. Perjalanan cahaya selalu memiliki jeda."},
    {"kind": "payoff", "text": "Bahkan cahaya Bulan memerlukan sekitar satu koma tiga detik untuk tiba di Bumi. Alam semesta yang terlihat adalah kumpulan pesan dari masa lalu."},
]
_demo_script["verification_status"] = "needs_review"
FIXTURES["script"] = json.dumps(_demo_script)
FIXTURES["creative_review"] = json.dumps({"verdict": "approve", "weak_spots": [], "revisions": [], "notes": "Demo fixture, not a live editorial review."})
_demo_scenes = []
for _i, _segment in enumerate(_demo_script["segments"]):
    _demo_scenes.append({
        "sceneId": f"scene-{_i + 1:02d}",
        "template": "KineticTypography" if _i in (0, 3) else "EducationalExplainer",
        "segment": _segment["text"], "assetRefs": [],
        "text": [{"id": f"title-{_i}", "text": ["Cahaya dari Masa Lalu", "Matahari ke Bumi", "Melihat Masa Lalu", "1,3 Detik dari Bulan"][_i],
                  "style": {"role": "title"}}],
        "animation": {"preset": "slideUp", "durationInFrames": 22},
        "transition": {"type": "fade", "durationInFrames": 8},
        "startFrame": _i * 270, "durationInFrames": 270,
        "data": {"bullets": [["Cahaya tidak tiba seketika"], ["Jarak rata-rata: 149,6 juta km", "Kecepatan: sekitar 300.000 km/detik"],
                              ["Perjalanan cahaya memerlukan waktu", "Yang terlihat sudah terjadi"], ["Bulan: sekitar 1,3 detik"]][_i]},
    })
FIXTURES["storyboard"] = json.dumps({"storyboard": {"id": "sb-demo", "fps": 30, "width": 1080, "height": 1920,
                                                   "language": "id-ID", "theme": {"id": "midnight"}, "scenes": _demo_scenes}})


class MockProvider:
    name = "mock"
    tier: Tier = "worker"

    def __init__(self, overrides: dict[str, str] | None = None, *, latency_ms: int = 0) -> None:
        self.fixtures = dict(FIXTURES)
        if overrides:
            self.fixtures.update(overrides)
        self.latency_ms = latency_ms
        self.calls: list[dict[str, Any]] = []

    def healthy(self) -> bool:
        return True

    def complete(self, *, task: str, system: str, user: str) -> ProviderResult:
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000)
        content = self.fixtures.get(task)
        if content is None:
            raise KeyError(f"no mock fixture for task {task!r}")
        self.calls.append({"task": task, "system_len": len(system), "user_len": len(user)})
        return ProviderResult(
            content=content,
            provider=self.name,
            model="mock-v1",
            prompt_tokens=max(1, len(system) // 4),
            completion_tokens=max(1, len(content) // 4),
            elapsed_ms=self.latency_ms,
            raw={"task": task, "mock": True},
        )
