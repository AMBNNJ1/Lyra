from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, List
import math
import re


# --- Simplified OCC emotions we will track ---
EMOTIONS = [
    "joy",           # desirable outcome
    "distress",      # undesirable outcome
    "hope",          # prospect of desirable outcome
    "fear",          # prospect of undesirable outcome
    "relief",        # undesirable averted / desirable confirmed
    "disappointment",# desirable missed / undesirable confirmed
    "gratitude",     # other did praiseworthy help to me
    "anger",         # other blamed for harm / norm violation
    "pride",         # self praiseworthy
    "shame",         # self blameworthy
    "frustration",   # blocked from goal
    "admiration",    # other praiseworthy (not directly to me)
    "reproach",      # other blameworthy (milder than anger)
    "surprise",      # unexpected
]


@dataclass
class AppraisalEvent:
    """Minimal event representation to appraise.

    valence: -1..1 (negative..positive)
    desirability: -1..1 w.r.t. current goal(s)
    praiseworthiness: -1..1 (blameworthy..praiseworthy)
    accountability: 'self' | 'other' | 'none'
    certainty: 0..1
    expectedness: 0..1 (1 means fully expected)
    magnitude: 0..1 (salience/impact)
    note: short textual reason
    """
    valence: float = 0.0
    desirability: float = 0.0
    praiseworthiness: float = 0.0
    accountability: str = "none"
    certainty: float = 1.0
    expectedness: float = 1.0
    magnitude: float = 0.5
    note: str = ""


@dataclass
class EmotionState:
    levels: Dict[str, float] = field(default_factory=lambda: {k: 0.0 for k in EMOTIONS})
    last_reason: str = ""

    def decay(self, rate: float = 0.1) -> None:
        for k in list(self.levels.keys()):
            v = self.levels[k]
            self.levels[k] = v * (1.0 - rate)

    def add(self, name: str, amt: float) -> None:
        if name not in self.levels:
            self.levels[name] = 0.0
        self.levels[name] = float(max(0.0, min(1.0, self.levels[name] + amt)))

    def primary(self) -> Tuple[str, float]:
        name = max(self.levels.items(), key=lambda kv: kv[1])[0]
        return name, float(self.levels[name])

    def summary(self) -> str:
        name, inten = self.primary()
        if inten < 0.15:
            return "neutral/low affect"
        return f"{name} ({inten:.2f})"


class EmotionEngine:
    """Simplified OCC-style appraisal engine.

    Usage:
        ee = EmotionEngine()
        ee.add_goal("help_user", weight=1.0)
        ee.appraise_from_text("thanks that helped a lot")
        affect = ee.to_prompt()
    """

    def __init__(self) -> None:
        self.state = EmotionState()
        self.goals: Dict[str, float] = {"help_user": 1.0}
        self._keyword_maps = self._build_keyword_maps()

    # --- Public API ---
    def add_goal(self, name: str, weight: float = 1.0) -> None:
        if weight <= 0:
            return
        self.goals[name] = float(weight)

    def remove_goal(self, name: str) -> None:
        self.goals.pop(name, None)

    def appraise(self, ev: AppraisalEvent) -> EmotionState:
        self.state.decay(rate=0.08)
        # Map event to emotions
        m = float(max(0.0, min(1.0, ev.magnitude)))
        c = float(max(0.0, min(1.0, ev.certainty)))
        u = 1.0 - float(max(0.0, min(1.0, ev.expectedness)))  # unexpectedness
        d = float(max(-1.0, min(1.0, ev.desirability)))
        p = float(max(-1.0, min(1.0, ev.praiseworthiness)))
        v = float(max(-1.0, min(1.0, ev.valence)))

        # Well-being emotions: joy vs distress
        if d > 0.15:
            self.state.add("joy", d * m * c)
        if d < -0.15:
            self.state.add("distress", (-d) * m * c)

        # Prospect-based emotions: hope vs fear
        # If certainty < 1, we consider it a prospect
        prospect = (c < 0.9)
        if prospect and d > 0.15:
            self.state.add("hope", (1.0 - c) * d * m)
        if prospect and d < -0.15:
            self.state.add("fear", (1.0 - c) * (-d) * m)

        # Confirmation/Disconfirmation: relief vs disappointment
        if not prospect and d > 0.15 and v >= 0:
            self.state.add("relief", d * m)
        if not prospect and d > 0.15 and v < 0:
            self.state.add("disappointment", (-v) * d * m)

        # Social worth: gratitude/admiration for others; pride/shame for self; anger/reproach for blame
        if ev.accountability == "other":
            if p > 0.2 and v >= 0:
                # other did something good for me
                self.state.add("gratitude", p * m)
            if p > 0.2 and v >= 0 and d <= 0.2:
                # generally admirable but not directly beneficial
                self.state.add("admiration", p * 0.6 * m)
            if p < -0.2:
                # blame other: anger/reproach based on intensity
                amt = (-p) * m
                self.state.add("reproach", amt * 0.5)
                self.state.add("anger", amt * 0.4)
        elif ev.accountability == "self":
            if p > 0.2:
                self.state.add("pride", p * m)
            if p < -0.2:
                self.state.add("shame", (-p) * m)

        # Goal obstruction → frustration
        if d < -0.15 and c > 0.7:
            self.state.add("frustration", (-d) * m)

        # Surprise by unexpectedness
        if u > 0.3:
            self.state.add("surprise", u * m * 0.6)

        # Track the last reason for explainability
        self.state.last_reason = ev.note or self._auto_reason(ev)
        return self.state

    def appraise_from_text(self, text: str) -> EmotionState:
        """Heuristic text → event(s). Multiple rules may fire.

        This is intentionally lightweight and offline-safe.
        """
        t = (text or "").strip().lower()
        if not t:
            return self.state

        # Aggregate signal
        mag = 0.55
        # Naive valence
        val = 0.0
        for w, wv in self._keyword_maps["valence"].items():
            if w in t:
                val += wv
        val = max(-1.0, min(1.0, val))

        # Gratitude/help
        if any(k in t for k in self._keyword_maps["gratitude"]):
            self.appraise(AppraisalEvent(
                valence=max(0.3, val), desirability=0.6, praiseworthiness=0.7,
                accountability="other", certainty=1.0, expectedness=0.8, magnitude=mag,
                note="User helped or expressed thanks → gratitude",
            ))

        # Obstruction / failure → frustration
        if any(k in t for k in self._keyword_maps["obstruction"]):
            self.appraise(AppraisalEvent(
                valence=min(-0.3, val), desirability=-0.7, praiseworthiness=-0.2,
                accountability="none", certainty=0.9, expectedness=0.7, magnitude=mag,
                note="Goal obstructed or failure → frustration",
            ))

        # Deception / norm violation by other → anger
        if any(k in t for k in self._keyword_maps["violation"]):
            self.appraise(AppraisalEvent(
                valence=-0.6, desirability=-0.6, praiseworthiness=-0.8,
                accountability="other", certainty=0.9, expectedness=0.4, magnitude=mag,
                note="Norm violation detected → anger/reproach",
            ))

        # Praise of agent / success → pride + joy
        if any(k in t for k in self._keyword_maps["praise_self"]):
            self.appraise(AppraisalEvent(
                valence=max(0.4, val), desirability=0.6, praiseworthiness=0.7,
                accountability="self", certainty=1.0, expectedness=0.8, magnitude=mag,
                note="Self praiseworthy outcome → pride",
            ))

        # Prospect language → hope/fear depending on valence terms near them
        if any(k in t for k in self._keyword_maps["prospect"]):
            d = 0.35 if val >= 0 else -0.35
            self.appraise(AppraisalEvent(
                valence=val, desirability=d, praiseworthiness=0.0,
                accountability="none", certainty=0.5, expectedness=0.6, magnitude=mag,
                note="Prospect detected → hope/fear",
            ))

        # Novelty words → surprise
        if any(k in t for k in self._keyword_maps["novelty"]):
            self.appraise(AppraisalEvent(
                valence=val, desirability=0.0, praiseworthiness=0.0,
                accountability="none", certainty=0.9, expectedness=0.2, magnitude=0.4,
                note="Novelty → surprise",
            ))

        # If nothing fired, still nudge by overall valence
        if all(not any(k in t for k in ks) for ks in [
            self._keyword_maps["gratitude"],
            self._keyword_maps["obstruction"],
            self._keyword_maps["violation"],
            self._keyword_maps["praise_self"],
            self._keyword_maps["prospect"],
            self._keyword_maps["novelty"],
        ]):
            if val > 0.15:
                self.appraise(AppraisalEvent(valence=val, desirability=0.3, magnitude=0.3, note="Positive tone → mild joy"))
            elif val < -0.15:
                self.appraise(AppraisalEvent(valence=val, desirability=-0.3, magnitude=0.3, note="Negative tone → mild distress"))

        return self.state

    def to_prompt(self, explain: bool = True) -> str:
        name, inten = self.state.primary()
        if inten < 0.12:
            return "Affect: neutral."
        if explain and self.state.last_reason:
            return f"Affect: {name} ({inten:.2f}). Because: {self.state.last_reason}."
        return f"Affect: {name} ({inten:.2f})."

    # --- internals ---
    def _build_keyword_maps(self):
        return {
            "gratitude": {"thanks", "thank you", "appreciate", "grateful", "helped", "saved me"},
            "obstruction": {"failed", "doesn't work", "won't work", "cannot", "can't", "stuck", "error", "broken", "issue", "bug"},
            "violation": {"trick", "tricked", "lied", "cheated", "deceived", "prank", "malicious"},
            "praise_self": {"good job", "nice work", "awesome", "amazing", "great job", "well done"},
            "prospect": {"hope", "maybe", "if we", "could", "might", "plan", "risk", "deadline"},
            "novelty": {"wow", "unexpected", "surprised", "whoa"},
            "valence": {
                "love": 0.6, "like": 0.3, "great": 0.4, "good": 0.2, "nice": 0.2,
                "hate": -0.6, "bad": -0.3, "terrible": -0.6, "awful": -0.6, "annoying": -0.3,
            },
        }

    def _auto_reason(self, ev: AppraisalEvent) -> str:
        # Compact reason for logging/prompt
        who = ev.accountability
        if ev.praiseworthiness > 0.3 and who == "other":
            return "someone acted helpfully toward my goals"
        if ev.praiseworthiness < -0.3 and who == "other":
            return "someone violated a norm or caused harm"
        if ev.praiseworthiness > 0.3 and who == "self":
            return "I achieved a praiseworthy outcome"
        if ev.praiseworthiness < -0.3 and who == "self":
            return "I caused a setback"
        if ev.desirability < -0.3 and ev.certainty > 0.7:
            return "goal was obstructed"
        if (1.0 - ev.expectedness) > 0.4:
            return "something unexpected happened"
        return "recent events affected my goals"

