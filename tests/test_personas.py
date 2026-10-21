"""Agent roster metadata for the dashboard: each agent rendered as a persona."""

from packages.core.personas import AGENT_CLASSES, PERSONAS
from packages.core.studio import AGENT_KEYS


def test_personas_cover_every_agent_key():
    assert set(PERSONAS) == set(AGENT_KEYS)


def test_persona_has_presentable_fields():
    for key, persona in PERSONAS.items():
        assert persona["persona"].strip(), key
        assert persona["role"].strip(), key
        assert persona["description"].strip(), key
        assert persona["stage"].strip(), key
        assert persona["accent"].startswith("#") and len(persona["accent"]) == 7, key


def test_persona_tier_matches_agent_class():
    for key, cls in AGENT_CLASSES.items():
        assert PERSONAS[key]["tier"] == cls.tier, key


def test_creative_director_is_strategist_and_stage_matches_pipeline_order():
    assert PERSONAS["CreativeDirectorAgent"]["tier"] == "strategist"
    assert PERSONAS["ScriptAgent"]["stage"] == "SCRIPT_GENERATED"
    assert PERSONAS["StoryboardAgent"]["stage"] == "STORYBOARD_READY"
