"""Persona roster for the operator UI.

Each agent gets a presentable identity (persona, role, description, stage,
accent color) so the dashboard can render the pipeline as a team of people
instead of bare identifiers. Tier is read from the agent class so the roster
can never drift from the code that actually runs the pipeline.
"""

from __future__ import annotations

from .agents import (
    CreativeDirectorAgent,
    MetadataAgent,
    QualityAgent,
    ResearchAgent,
    ScriptAgent,
    StoryboardAgent,
    TopicSelectionAgent,
)

AGENT_CLASSES = {
    "ResearchAgent": ResearchAgent,
    "TopicSelectionAgent": TopicSelectionAgent,
    "ScriptAgent": ScriptAgent,
    "CreativeDirectorAgent": CreativeDirectorAgent,
    "StoryboardAgent": StoryboardAgent,
    "QualityAgent": QualityAgent,
    "MetadataAgent": MetadataAgent,
}

# Display-only fields; the pipeline itself never reads this mapping.
_PERSONA_FIELDS = {
    "ResearchAgent": {
        "persona": "Sang Peneliti",
        "role": "Riset & sumber",
        "description": "Mengais ide dari web, menyaring yang layak, mencatat sumber asli.",
        "stage": "IDEA_DISCOVERY",
        "accent": "#38bdf8",
    },
    "TopicSelectionAgent": {
        "persona": "Sang Kurator",
        "role": "Seleksi topik",
        "description": "Menilai kandidat: kebaruan, kekuatan hook, potensi visual.",
        "stage": "TOPIC_SELECTED",
        "accent": "#a78bfa",
    },
    "ScriptAgent": {
        "persona": "Sang Penulis",
        "role": "Naskah 30–45 detik",
        "description": "Merangkai hook tajam, badan padat, penutup yang memuaskan.",
        "stage": "SCRIPT_GENERATED",
        "accent": "#fbbf24",
    },
    "CreativeDirectorAgent": {
        "persona": "Sang Sutradara",
        "role": "Review kreatif",
        "description": "Menyunting naskah dengan ketat: hook lambat, payoff lemah, dan klise ditolak.",
        "stage": "CREATIVE_REVIEW",
        "accent": "#fb7185",
    },
    "StoryboardAgent": {
        "persona": "Sang Perancang",
        "role": "Papan cerita",
        "description": "Menerjemahkan naskah jadi SceneSpec[] tervalidasi untuk renderer.",
        "stage": "STORYBOARD_READY",
        "accent": "#34d399",
    },
    "QualityAgent": {
        "persona": "Sang Pengawas",
        "role": "QC teknis & editorial",
        "description": "Memeriksa naskah vs papan cerita; menandai titik lemah sebelum render final.",
        "stage": "TECHNICAL_QC",
        "accent": "#22d3ee",
    },
    "MetadataAgent": {
        "persona": "Sang Penyusun",
        "role": "Judul & kata kunci",
        "description": "Menyusun judul, deskripsi, keyword, dan konsep thumbnail.",
        "stage": "EDITORIAL_QC",
        "accent": "#f97316",
    },
}

PERSONAS: dict[str, dict[str, str]] = {
    key: {**fields, "tier": cls.tier}
    for key, fields in _PERSONA_FIELDS.items()
    for cls in (AGENT_CLASSES[key],)
}
