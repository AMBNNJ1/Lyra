# Lyra Emotion Engine

Lyra adds a touch of personality by tracking a lightweight emotional state. The same engine drives the affect line shown to the LLM and can be used to trigger avatar animations or voice inflection.

## How It Works

- **Model** ? `src/neuro_mvp/emotion.py` implements a simplified OCC appraisal system.
- **Inputs** ? user text (via keyword heuristics) and optional structured events raised by the backend.
- **Outputs** ? `EmotionState` with intensity for emotions such as joy, frustration, gratitude, anger, and surprise, plus a short ?Because ?? explanation.
- **Decay** ? each turn decays previous intensities so fresh events dominate.

## Integration Points

| Stage | Usage |
|-------|-------|
| Prompting | `ee.to_prompt()` returns a string like `Affect: gratitude (0.42). Because: user thanked me for the help.` appended to the system message. |
| Avatar | Map the primary emotion to CSS classes or video swaps in `web/index.html` (e.g., show a smiling still when joy > 0.3). |
| Memory | Significant affect changes can be logged into Mem0 to explain why decisions were made. |
| Voice | Adjust Kokoro TTS parameters (rate/pitch) based on intensity if you want more expressive playback. |

## Quick Start

```python
from neuro_mvp.emotion import EmotionEngine

ee = EmotionEngine()

ee.appraise_from_text("thanks, that really helped!")
print(ee.to_prompt())  # Affect: gratitude (0.xx). Because: User helped or expressed thanks ...
```

You can also craft explicit `AppraisalEvent` objects when a tool call or search result suggests a strong outcome (success, failure, norm violation, etc.).

## Customisation

- Extend keyword sets in `_build_keyword_maps` for your domain-specific vocabulary.
- Tune decay rate in `EmotionState.decay` to make the avatar more or less reactive.
- Add new emotion labels by updating `EMOTIONS` and the response logic (be sure to surface them in the UI).

Emotion is optional but enriches repeat conversations?Lyra can remember what happened, cite why she feels a certain way, and react visually on the chat page.
