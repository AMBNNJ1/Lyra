Lyra — Zoom-like Homepage with 3D Avatar
========================================

What it is
----------
- A modern, Zoom/Teams-style single-page UI to showcase an AI avatar.
- Loads a `.glb` 3D model and displays it in a stage.
- Basic controls (mute, video pause overlay, background cycle, recenter, chat panel).

Run locally
-----------
1. From the repo root, serve the folder to avoid browser CORS when importing Three.js modules:

   - Python: `python -m http.server 5500 -d web/lyra`
   - Node (http-server): `npx http-server web/lyra -p 5500`

2. Open http://localhost:5500/ in your browser.

3. Drag-and-drop a `.glb` into the stage, or click "Load Model" and pick your file.

Auto‑loading a model
--------------------
- Easiest: copy your model into `web/lyra/assets/` and name it one of:
  - `hina.glb`
  - `hina_3d_anime_character_girl_for_blender.glb`
  - `avatar.glb`
  The page will auto‑load the first one it finds on startup.

- Or pass a query param:
  - `http://localhost:5500/?model=assets/hina_3d_anime_character_girl_for_blender.glb`
  - You can also host a remote URL if it is CORS‑accessible.

Notes
-----
- Three.js is imported from unpkg CDN. An internet connection is required to load the modules.
- You can customize styles in `web/lyra/styles.css`.
- Add your default model or assets to `web/lyra/` and optionally auto-load via a small change in `app.js`.
