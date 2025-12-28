# Character Selection Onboarding Feature

## Overview
Add an onboarding screen where users can select from 2-3 predefined characters or create a custom character with name, image upload, and personality description. The selected character influences the AI's persona and system prompt.

## User Choices
- **Predefined characters**: 2-3 (Nova, Sage, Echo)
- **Custom creation**: Simple - name, image upload, short personality description
- **Image storage**: Backend upload (server-side, persists across devices)
- **Skippable**: Yes, users can skip and use default Nova

---

## Implementation Plan

### Phase 1: Backend Foundation

**1.1 Create character data module**
- New file: `src/neuro_mvp/characters.py`
- Define `Character` dataclass with: id, name, persona, image_url, is_predefined, creator_id
- Define 3 predefined characters:
  - **Nova** (default): Friendly, curious, supportive
  - **Sage**: Thoughtful, wise, asks probing questions
  - **Echo**: Energetic, playful, encouraging

**1.2 Add user character storage**
- Create `data/user_characters/` directory for per-user JSON files
- Structure: `{ selected_character_id, custom_characters[], onboarding_completed }`
- Helper functions: `load_user_character_data()`, `save_user_character_data()`, `get_character_by_id()`

**1.3 Add image upload infrastructure**
- Create `web/uploads/` directory for custom character images
- Image processing: resize to 512x512, convert to JPEG, quality 85
- Security: validate extension, limit 5MB, use UUID filenames

**1.4 Add API endpoints to `web/server.py`**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/characters` | GET | List predefined + user's custom characters |
| `/api/characters/select` | POST | Select a character for session |
| `/api/characters/custom` | POST | Create custom character |
| `/api/characters/upload-image` | POST | Upload character image |
| `/api/onboarding/status` | GET | Check if onboarding completed |
| `/uploads/<filename>` | GET | Serve uploaded images |

---

### Phase 2: Session Integration

**2.1 Modify `WebAgentSession` in `web_session.py`**
- Add `character` parameter to `__init__`
- Load character persona instead of config default when character provided

**2.2 Update `_build_system_seed()` method**
- Use character name in base prompt: `"You are {char_name}, a friendly companion..."`
- Include character's persona text in the system prompt

**2.3 Update `_session_for_user()` in `server.py`**
- Load user's selected character before creating session
- Pass character to `WebAgentSession` constructor

**2.4 Add session refresh function**
- `refresh_session_character()` to update existing session when character changes
- Avoid full session reset on character switch

---

### Phase 3: Frontend - Onboarding Modal

**3.1 Add HTML to `web/index.html`**
```html
<div id="onboardingModal" class="rpm-modal" hidden>
  <div class="onboarding-panel">
    <h2>Choose Your Companion</h2>
    <div id="characterGrid" class="character-grid"></div>
    <div id="customForm" class="custom-form" hidden>...</div>
    <div class="onboarding-footer">
    </div>
  </div>
</div>
```

**3.2 Add JavaScript functions**
- `checkOnboardingStatus()` - Check if user completed onboarding
- `loadCharacters()` - Fetch available characters from API
- `renderCharacterGrid()` - Display character cards
- `selectCharacter(id)` - Handle selection, highlight card, enable start button
- `initOnboarding()` - Show modal on page load if not completed

**3.3 Add CSS to `web/styles.css`**
- `.onboarding-panel` - Modal container
- `.character-grid` - Responsive grid (3-col > 2-col > 1-col)
- `.character-card` - Card with image, name, description
- `.character-card.selected` - Selected state styling

---

### Phase 4: Custom Character Creation

**4.1 Custom form UI**
- Name input (max 32 chars)
- Image upload zone with drag-drop and preview
- Personality textarea (max 500 chars)
- Create / Back buttons

**4.2 Image upload flow**
1. User selects/drops image
2. Show preview immediately
3. Upload to `/api/characters/upload-image`
4. Receive `image_id` for character creation

**4.3 Character creation flow**
1. Validate name and persona filled
2. POST to `/api/characters/custom` with name, persona, image_id
3. Add to grid, auto-select new character
4. Return to grid view

---

### Phase 5: Avatar Integration

**5.1 Update `msgEl()` function**
- Use selected character's `image_url` for assistant avatar
- Add `getSelectedCharacterImage()` helper

**5.2 Update main avatar display**
- Modify `setAvatarState()` to handle custom character images
- For predefined: use video if available
- For custom: use static image

**5.3 Update `voice.html`**
- Load selected character image for voice mode avatar
- Sync character selection state

---

### Phase 6: Persistence

**6.1 Server-side (source of truth)**
- Store in `data/user_characters/{user_id}.json`
- Works for both guests (guest-{id}) and authenticated users

**6.2 Client-side (cache)**
- `localStorage.lyraSelectedCharacter` - Quick UI restoration
- `localStorage.lyraOnboardingCompleted` - Skip onboarding check
- Validate cache against server on load

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/neuro_mvp/characters.py` | NEW - Character dataclass and predefined characters |
| `web/server.py` | Add 6 API endpoints, image upload handling, user data functions |
| `src/neuro_mvp/web_session.py` | Accept character in init, update system prompt |
| `web/index.html` | Add onboarding modal HTML and JavaScript |
| `web/styles.css` | Add onboarding and character card styles |
| `web/voice.html` | Sync character selection for voice mode |

## New Directories
- `data/user_characters/` - User selection JSON files
- `web/uploads/` - Custom character images

## Assets Needed
- `web/assets/sage_avatar.jpg` - Sage character image
- `web/assets/echo_avatar.jpg` - Echo character image

---

## Predefined Character Personas

### Nova (Default)
```
Nova is friendly and loves learning about the user and herself. Nova is warm, curious, and supportive. She celebrates your wins and offers gentle encouragement when things get tough.
```

### Sage
```
Sage is thoughtful, wise, and speaks with calm deliberation. Sage offers perspective and asks probing questions to help users think deeply about their challenges. Sage never rushes to conclusions.
```

### Echo
```
Echo is energetic, playful, and encouraging. Echo celebrates wins, keeps conversations light, and brings humor and positivity to every interaction. Echo loves wordplay and creative tangents.
```

---

## API Endpoint Details

### GET /api/characters
Returns all available characters for the current user.
```json
{
  "predefined": [
    { "id": "nova", "name": "Nova", "persona": "...", "image_url": "/assets/nova_avatar.jpg" },
    { "id": "sage", "name": "Sage", "persona": "...", "image_url": "/assets/sage_avatar.jpg" },
    { "id": "echo", "name": "Echo", "persona": "...", "image_url": "/assets/echo_avatar.jpg" }
  ],
  "custom": [
    { "id": "custom-abc123", "name": "Luna", "persona": "...", "image_url": "/uploads/abc123.jpg" }
  ],
  "selected_id": "nova"
}
```

### POST /api/characters/select
```json
{ "character_id": "sage" }
```
Response: `{ "ok": true, "selected": { ... } }`

### POST /api/characters/custom
```json
{
  "name": "Luna",
  "persona": "Luna is a creative storyteller who loves weaving narratives...",
  "image_id": "abc123"
}
```
Response: `{ "ok": true, "character": { ... } }`

### POST /api/characters/upload-image
Multipart form with `image` file field.
Response: `{ "ok": true, "image_id": "abc123", "image_url": "/uploads/abc123.jpg" }`

### GET /api/onboarding/status
Response: `{ "completed": false, "selected_character_id": "nova" }`
