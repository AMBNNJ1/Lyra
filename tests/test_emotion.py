import math

from neuro_mvp.emotion import EmotionEngine, AppraisalEvent


def test_appraise_event_increases_joy():
    engine = EmotionEngine()
    event = AppraisalEvent(
        valence=0.8,
        desirability=0.9,
        praiseworthiness=0.0,
        accountability="none",
        certainty=1.0,
        expectedness=1.0,
        magnitude=0.7,
        note="positive outcome",
    )

    state = engine.appraise(event)

    assert state.levels["joy"] > 0
    assert math.isclose(state.levels["joy"], engine.state.levels["joy"])
    assert state.last_reason == "positive outcome"


def test_appraise_from_text_triggers_gratitude_and_frustration():
    engine = EmotionEngine()
    engine.appraise_from_text("Thank you so much for the help, but I am still stuck on this bug")

    assert engine.state.levels["gratitude"] > 0
    assert engine.state.levels["frustration"] > 0


def test_state_decay_and_primary():
    engine = EmotionEngine()
    engine.state.levels["joy"] = 1.0

    engine.state.decay(rate=0.2)
    name, intensity = engine.state.primary()

    assert name == "joy"
    assert intensity == engine.state.levels["joy"]
    assert math.isclose(intensity, 0.8, rel_tol=1e-6)
