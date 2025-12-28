Place your avatar media here:

## Nova (default character)
- Static image poster: `nova_avatar.jpg`
- Video loop (preferred): `nova_video.mp4`
- Hero video: `nova_hero.mp4`

## Sage character
- Static image: `sage_avatar.png` (512x512 PNG)
  - Personality: Thoughtful, wise, serene appearance

## Echo character
- Static image: `echo_avatar.png` (512x512 PNG)
  - Personality: Energetic, playful appearance

The chat page references these at:
  /assets/nova_video.mp4  (autoplay muted loop)
  /assets/nova_avatar.jpg  (poster / fallback)
  /assets/sage_avatar.png  (Sage character)
  /assets/echo_avatar.png  (Echo character)

Custom character images are stored in /web/uploads/ after being
resized to 512x512 by the server.

If you change filenames, update `src/neuro_mvp/characters.py` accordingly.
