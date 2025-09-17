Lyra Emotional Framework — Simplified OCC Rules
==============================================

Overview
--------
- Approach: OCC-style appraisal (Ortony, Clore, Collins), simplified for real-time agents.
- Idea: Emotions are computed from appraisals of events relative to goals, norms, and accountability.
- Why: Adds personality and explainability (e.g., “I’m upset because you tricked me”).

Pros
----
- Adds context-dependent richness and coherent reactions.
- Lightweight, offline-safe, no external models required.
- Explainable: returns a short “Because …” reason to include in prompts or logs.

Cons
----
- Needs rule coverage; edge cases require iteration.
- Consistency depends on tuning magnitudes and decay.

Concepts
--------
- Goals: What the agent cares about (default: `help_user: 1.0`).
- Appraisal event: `valence`, `desirability`, `praiseworthiness`, `accountability` (self/other/none), `certainty`, `expectedness`, `magnitude`.
- Emotions tracked (subset): joy, distress, hope, fear, relief, disappointment, gratitude, anger, pride, shame, frustration, admiration, reproach, surprise.
- Dynamics: Per-turn decay; multiple rules/events can accumulate.

Event Schema
------------
```
AppraisalEvent(
  valence:        -1..1,     # general positive/negative tone
  desirability:   -1..1,     # effect relative to goals
  praiseworthiness:-1..1,    # norm-based judgment
  accountability:  'self'|'other'|'none',
  certainty:      0..1,      # 1 means confirmed; <1 means prospective
  expectedness:   0..1,      # 1 expected, 0 surprising
  magnitude:      0..1,      # salience/impact
  note:           str        # human-readable reason
)
```

Core Rules (Simplified)
-----------------------
- Well-being: desirability>0 → joy; desirability<0 → distress.
- Prospect: (certainty<0.9) & desirability>0 → hope; (certainty<0.9) & desirability<0 → fear.
- Outcome confirmation: relief vs disappointment depending on outcome vs expectation.
- Social worth: other+praiseworthy → gratitude/admiration; self+praiseworthy → pride; self/other+blameworthy → shame/reproach/anger.
- Goal obstruction (desirability<0 & certain) → frustration.
- Unexpectedness → surprise.

Text Heuristics
---------------
- Gratitude/help: “thanks”, “appreciate”, “helped”, “saved me”.
- Obstruction: “failed”, “can’t”, “stuck”, “error”, “broken”, “issue”.
- Norm violation: “tricked”, “lied”, “cheated”, “deceived”, “prank”.
- Praise (self): “good job”, “well done”, “amazing”, “awesome”.
- Prospect: “hope”, “maybe”, “could”, “might”, “plan”, “deadline”, “risk”.
- Novelty: “wow”, “unexpected”, “surprised”.

Integration Points
------------------
- Prompting: prepend a one-line affect hint to the system message (e.g., `Affect: anger (0.42). Because: …`).
- VTS/Avatar: map primary emotion to expression hotkeys; use arousal/intensity for strength.
- TTS: modulate prosody (rate/pitch) based on intensity (e.g., frustration → faster rate, higher energy).
- Memory: optionally record major affect shifts as working context facts.

API (Python)
------------
- Module: `src/neuro_mvp/emotion.py`
- Class: `EmotionEngine`
- Methods:
  - `add_goal(name, weight)` – register goals.
  - `appraise(event)` – apply a structured event.
  - `appraise_from_text(text)` – heuristic text-based rules.
  - `to_prompt(explain=True)` – produce a concise affect line for prompting/logging.

Usage Example
-------------
```python
from src.neuro_mvp.emotion import EmotionEngine

ee = EmotionEngine()
ee.add_goal("help_user", 1.0)

# From user input
ee.appraise_from_text("thanks, that really helped!")
print(ee.to_prompt())  # -> Affect: gratitude (0.xx). Because: User helped or expressed thanks …

# Structured event
from src.neuro_mvp.emotion import AppraisalEvent
ee.appraise(AppraisalEvent(
    valence=-0.5, desirability=-0.7, praiseworthiness=-0.6,
    accountability="other", certainty=0.95, expectedness=0.5, magnitude=0.8,
    note="Build was broken due to someone’s mistake",
))
print(ee.to_prompt())
```

Minimal Prompt Hook
-------------------
In your loop, include the affect line in the system message:
```
affect = ee.to_prompt()
system = base_system + "\n" + affect + other_context
```

Next Steps
----------
- Expand keyword sets and add domain rules (e.g., project management, code build states).
- Add arousal/valence → VTS expression map with intensity scaling.
- Optionally persist `ee.state.levels` in memory to carry affect across sessions.

