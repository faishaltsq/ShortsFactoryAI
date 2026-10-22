"""Persona roster for the operator UI.

Each agent gets a presentable identity so the dashboard can render the pipeline
as a team of people instead of bare identifiers: name, role, personality,
motto, workstation zone, and the pixel-art accessory that makes the character
recognizable at 32px.

Two views exist on purpose:

``PERSONAS``
    The seven agents whose system prompt the operator can edit. Shape is
    unchanged so ``/api/studio`` and the Studio editor keep working.

``TEAM``
    Every role in the pipeline, including the five deterministic stages that
    have no editable prompt. Display only.

Tier is read from the agent class so the roster can never drift from the code
that actually runs the pipeline. Nothing here is fed to a model: names and
mottos are presentation, never system-prompt text.
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

# key, name, role, description, stage, accent, zone, personality, motto,
# accessory, hair, skin
_ROWS = (
    ("FactoryOrchestrator", "Arka", "Koordinator studio", "Menjaga urutan kerja, budget, dan titik henti.", "CONTROL", "#f4bc68", "Ruang kendali", "Tenang, teratur, selalu melihat gambaran besar.", "Satu langkah jelas, satu hasil nyata.", "headset", "short", "warm"),
    ("ResearchAgent", "Raka", "Peneliti", "Mengumpulkan kandidat ide dan mencatat sumber; verifikasi fakta tetap terpisah.", "IDEA_DISCOVERY", "#6dc7e8", "Ide & cerita", "Penasaran, skeptis, rajin mencatat.", "Menarik saja belum cukup; cari sumbernya.", "goggles", "curls", "deep"),
    ("TopicSelectionAgent", "Nara", "Kurator topik", "Memilih ide dari kebaruan, hook, dan potensi visual.", "TOPIC_SELECTED", "#b8a2e3", "Ide & cerita", "Selektif, tajam, tidak mudah ikut tren.", "Pilih satu ide yang pantas ditonton.", "beret", "bob", "light"),
    ("ScriptAgent", "Sora", "Penulis naskah", "Menyusun hook, perkembangan cerita, dan payoff.", "SCRIPT_GENERATED", "#f4ce72", "Ide & cerita", "Ringkas, imajinatif, peka pada ritme.", "Kalimat pertama harus membuat orang tinggal.", "pencil", "ponytail", "warm"),
    ("CreativeDirectorAgent", "Vega", "Sutradara kreatif", "Menguji ide, membedah naskah, dan memperkuat payoff.", "CREATIVE_REVIEW", "#ed91a4", "Ide & cerita", "Berani, terus terang, menuntut alasan kreatif.", "Bagus itu awal; berkesan itu tujuan.", "cap", "short", "deep"),
    ("StoryboardAgent", "Luma", "Perancang storyboard", "Menerjemahkan naskah menjadi SceneSpec yang tervalidasi.", "STORYBOARD_READY", "#82cda7", "Produksi", "Visual, teliti, suka membuat hal rumit terbaca.", "Satu adegan, satu gagasan yang terlihat.", "visor", "bob", "warm"),
    ("AssetAgent", "Bimo", "Penata aset", "Menyiapkan aset lokal yang didukung renderer.", "ASSETS_READY", "#e6ad78", "Produksi", "Praktis, rapi, peduli detail kecil.", "Setiap benda punya tempatnya.", "scarf", "curls", "deep"),
    ("AudioAgent", "Nada", "Penata suara", "Menyiapkan narasi, timing nyata, dan subtitle.", "AUDIO_READY", "#93b8ea", "Produksi", "Sabar, musikal, peka pada jeda.", "Cerita juga hidup di antara kata.", "headphones", "ponytail", "light"),
    ("RenderAgent", "Rendi", "Teknisi render", "Merakit video dan menjalankan pemeriksaan media teknis.", "RENDERING", "#89c9cf", "Produksi", "Tekun, logis, tidak menganggap selesai sebelum diperiksa.", "Bukan cuma jadi; hasilnya harus bisa diputar.", "wrench", "short", "warm"),
    ("QualityAgent", "Tera", "Peninjau draft", "Menilai konsistensi naskah dan storyboard sebelum render.", "TECHNICAL_QC", "#a2cf95", "Pemeriksaan & rilis", "Kritis, adil, lebih suka bukti daripada asumsi.", "Cek lagi sebelum melangkah.", "glasses", "bob", "deep"),
    ("MetadataAgent", "Mika", "Editor metadata", "Menyusun judul, deskripsi, kata kunci, dan konsep thumbnail.", "EDITORIAL_QC", "#efa782", "Pemeriksaan & rilis", "Cermat, komunikatif, peka pada pilihan kata.", "Kemasan jujur membuat cerita mudah ditemukan.", "pin", "curls", "light"),
    ("PublishAgent", "Kira", "Penjaga rilis", "Peran publikasi yang direncanakan; belum tersedia di workspace ini.", "PRIVATE_UPLOAD", "#a9b2c5", "Pemeriksaan & rilis", "Hati-hati, disiplin, menghormati keputusan operator.", "Rilis hanya setelah lampu hijau operator.", "badge", "ponytail", "warm"),
)

_FIELDS = ("persona", "role", "description", "stage", "accent", "zone",
           "personality", "motto", "accessory", "hair", "skin")

# Every role in the pipeline, including the deterministic stages that have no
# editable prompt. Presentation only: never feed these names or mottos into a
# model system prompt.
TEAM: dict[str, dict[str, str | bool]] = {
    row[0]: {
        **dict(zip(_FIELDS, row[1:])),
        "tier": AGENT_CLASSES[row[0]].tier if row[0] in AGENT_CLASSES else "deterministic",
        "editable": row[0] in AGENT_CLASSES,
        "available": row[0] != "PublishAgent",
    }
    for row in _ROWS
}

# The seven agents whose system prompt the operator can edit. Same shape as
# before, so /api/studio and the Studio editor keep working unchanged.
PERSONAS: dict[str, dict[str, str | bool]] = {key: TEAM[key] for key in AGENT_CLASSES}
