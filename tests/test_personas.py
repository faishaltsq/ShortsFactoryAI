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


def test_full_team_is_distinct_and_keeps_configurable_subset():
    from packages.core.personas import TEAM

    assert set(TEAM) == set(AGENT_KEYS) | {
        "FactoryOrchestrator", "AssetAgent", "AudioAgent", "RenderAgent", "PublishAgent"
    }
    assert len({p["persona"] for p in TEAM.values()}) == len(TEAM)
    assert len({p["accessory"] for p in TEAM.values()}) == len(TEAM)
    assert {k for k, p in TEAM.items() if p["editable"]} == set(AGENT_KEYS)
    assert TEAM["PublishAgent"]["available"] is False
    for key, profile in TEAM.items():
        for field in ("personality", "motto", "zone", "accessory", "hair", "skin"):
            assert profile[field], (key, field)
        if key in AGENT_CLASSES:
            assert profile["tier"] == AGENT_CLASSES[key].tier
