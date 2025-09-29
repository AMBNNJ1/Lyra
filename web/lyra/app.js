// Lyra: Zoom-like stage with 3D GLB avatar
// Uses Three.js modules via unpkg CDN

import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';
import { GLTFLoader } from 'https://unpkg.com/three@0.160.0/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'https://unpkg.com/three@0.160.0/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'https://unpkg.com/three@0.160.0/examples/jsm/environments/RoomEnvironment.js';

let renderer, scene, camera, controls;
let pmrem, envTex;
let avatarGroup = null; // holds current model
let stageEl, canvasEl, dropHintEl, pausedOverlayEl;
let rpmModalEl, rpmFrameEl, rpmCloseBtn, createAvatarBtn;
let rpmSubscribed = false;

const state = {
  bgMode: 0, // 0: gradient, 1: solid, 2: aurora
  videoPaused: false,
  muted: false
};

init();
animate();

// Auto-load model from query param or a default asset if present
(async () => {
  try {
    const u = new URL(window.location.href);
    const m = u.searchParams.get('model');
    if (m) {
      await loadModel(m);
      return;
    }
    // Load last Ready Player Me avatar if stored
    const saved = localStorage.getItem('rpmAvatarUrl');
    if (saved && await headExists(saved)){
      await loadModel(saved);
      return;
    }
    // Try a few common filenames under ./assets/ if no query provided
    const candidates = [
      './assets/hina.glb',
      './assets/hina_3d_anime_character_girl_for_blender.glb',
      './assets/avatar.glb'
    ];
    for (const c of candidates) {
      const ok = await headExists(c);
      if (ok) { await loadModel(c); break; }
    }
  } catch (e) {
    // ignore auto-load failures
  }
})();

async function headExists(url) {
  try {
    const res = await fetch(url, { method: 'HEAD', cache: 'no-cache' });
    return res.ok;
  } catch {
    return false;
  }
}

function init(){
  stageEl = document.getElementById('stage');
  canvasEl = document.getElementById('three');
  dropHintEl = document.getElementById('dropHint');
  pausedOverlayEl = document.getElementById('pausedOverlay');
  rpmModalEl = document.getElementById('rpmModal');
  rpmFrameEl = document.getElementById('rpmFrame');
  rpmCloseBtn = document.getElementById('rpmClose');
  createAvatarBtn = document.getElementById('createAvatarBtn');

  renderer = new THREE.WebGLRenderer({ canvas: canvasEl, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  resize();

  scene = new THREE.Scene();

  camera = new THREE.PerspectiveCamera(40, stageEl.clientWidth / stageEl.clientHeight, 0.1, 100);
  camera.position.set(0.6, 1.2, 2.2);

  controls = new OrbitControls(camera, stageEl);
  controls.enableDamping = true;
  controls.target.set(0, 1.3, 0);

  pmrem = new THREE.PMREMGenerator(renderer);
  envTex = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;
  scene.environment = envTex;
  scene.background = null; // CSS-driven background

  // Lights
  const hemi = new THREE.HemisphereLight(0xbfd3ff, 0x0b0f14, 0.6);
  scene.add(hemi);

  const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
  dirLight.position.set(2, 4, 2);
  dirLight.castShadow = true;
  dirLight.shadow.mapSize.set(2048, 2048);
  scene.add(dirLight);

  // Soft ground shadow
  const groundGeo = new THREE.PlaneGeometry(10, 10);
  const groundMat = new THREE.ShadowMaterial({ opacity: 0.2 });
  const ground = new THREE.Mesh(groundGeo, groundMat);
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = 0;
  ground.receiveShadow = true;
  scene.add(ground);

  // Drag & drop handlers
  ;['dragenter','dragover','dragleave','drop'].forEach(name => {
    stageEl.addEventListener(name, e => { e.preventDefault(); e.stopPropagation(); });
  });
  stageEl.addEventListener('dragover', () => stageEl.classList.add('dragging'));
  stageEl.addEventListener('dragleave', () => stageEl.classList.remove('dragging'));
  stageEl.addEventListener('drop', onDropFile);

  // UI wiring
  document.getElementById('modelFile').addEventListener('change', e => {
    const file = e.target.files && e.target.files[0];
    if (file) loadFromFile(file);
  });
  document.getElementById('recenterBtn').addEventListener('click', recenterCamera);
  document.getElementById('bgBtn').addEventListener('click', cycleBackground);
  document.getElementById('chatToggleBtn').addEventListener('click', toggleChat);
  document.getElementById('settingsBtn').addEventListener('click', () => alert('Settings placeholder'));
  document.getElementById('endBtn').addEventListener('click', () => {
    if (confirm('End session?')) window.location.reload();
  });

  if (createAvatarBtn) {
    createAvatarBtn.addEventListener('click', () => openReadyPlayerMe());
  }
  if (rpmCloseBtn) {
    rpmCloseBtn.addEventListener('click', () => closeReadyPlayerMe());
  }
  // handle ESC to close modal
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !rpmModalEl.hidden) closeReadyPlayerMe();
  });

  const muteBtn = document.getElementById('muteBtn');
  muteBtn.addEventListener('click', () => {
    state.muted = !state.muted;
    muteBtn.setAttribute('aria-pressed', String(state.muted));
    muteBtn.querySelector('.btn-label').textContent = state.muted ? 'Unmute' : 'Mute';
  });

  const videoBtn = document.getElementById('videoBtn');
  videoBtn.addEventListener('click', () => {
    state.videoPaused = !state.videoPaused;
    videoBtn.setAttribute('aria-pressed', String(state.videoPaused));
    pausedOverlayEl.hidden = !state.videoPaused;
  });

  // Upgrade chat UI to modern layout
  ensureModernChatUI();
  // Chat form
  const chatForm = document.getElementById('chatForm');
  const chatText = document.getElementById('chatText');
  const chatBody = document.getElementById('chatBody');
  chatForm.addEventListener('submit', e => {
    e.preventDefault();
    const txt = chatText.value.trim();
    if (!txt) return;
    chatBody.appendChild(msgCard(txt, 'you'));
    chatText.value = '';
    chatBody.scrollTop = chatBody.scrollHeight;
    // Placeholder echo from Lyra
    setTimeout(() => {
      chatBody.appendChild(msgCard('Got it: ' + txt, 'ai', 'auto'));
      chatBody.scrollTop = chatBody.scrollHeight;
    }, 400);
  });

  window.addEventListener('resize', resize);

  // Default background mode
  applyBackground();

  // Ready Player Me postMessage wiring
  setupReadyPlayerMeMessaging();
}

function animate(){
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}

function resize(){
  const w = stageEl.clientWidth;
  const h = stageEl.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

function onDropFile(e){
  stageEl.classList.remove('dragging');
  const dt = e.dataTransfer;
  if (!dt) return;
  const file = [...(dt.files || [])].find(f => /\.gl(b|tf)$/i.test(f.name));
  if (file) loadFromFile(file);
}

async function loadFromFile(file){
  const url = URL.createObjectURL(file);
  try { await loadModel(url); } finally { URL.revokeObjectURL(url); }
}

async function loadModel(url){
  dropHintEl.style.display = 'none';
  const loader = new GLTFLoader();
  const gltf = await loader.loadAsync(url);

  if (avatarGroup){
    scene.remove(avatarGroup);
    avatarGroup.traverse(obj => {
      if (obj.isMesh) { obj.geometry?.dispose(); obj.material?.dispose?.(); }
    });
  }

  avatarGroup = new THREE.Group();
  avatarGroup.add(gltf.scene);
  scene.add(avatarGroup);

  prepareModel(gltf.scene);
  recenterCamera();
}

function prepareModel(root){
  root.traverse(obj => {
    if (obj.isMesh){
      obj.castShadow = true;
      obj.receiveShadow = false;
      if (obj.material && obj.material.isMeshStandardMaterial){
        obj.material.envMapIntensity = 1.0;
      }
    }
  });
}

function recenterCamera(){
  if (!avatarGroup){ return; }
  const box = new THREE.Box3().setFromObject(avatarGroup);
  const size = new THREE.Vector3(); box.getSize(size);
  const center = new THREE.Vector3(); box.getCenter(center);

  // Move the group so its center is at origin
  avatarGroup.position.sub(center);

  // Compute a good distance based on bounding sphere
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const radius = sphere.radius;

  // Target head-ish height (if tall model)
  const height = size.y || 1.8;
  const desiredY = Math.min(Math.max(height * 0.65, 1.2), 2.2);

  const dist = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov * 0.5));
  const targetDist = THREE.MathUtils.clamp(dist * 1.2, 1.2, 6.5);

  controls.target.set(0, desiredY, 0);
  camera.position.set(targetDist * 0.3, desiredY + targetDist * 0.25, targetDist);
  controls.update();
}

function cycleBackground(){
  state.bgMode = (state.bgMode + 1) % 3; // 0..2
  applyBackground();
}

function applyBackground(){
  const body = document.body;
  body.classList.remove('bg-solid','bg-gradient','bg-aurora');
  if (state.bgMode === 0) body.classList.add('bg-gradient');
  else if (state.bgMode === 1) body.classList.add('bg-solid');
  else body.classList.add('bg-aurora');
}

function toggleChat(){
  const pane = document.getElementById('chatPane');
  const nowHidden = !pane.hidden;
  pane.hidden = nowHidden;
  // When showing chat, switch to chat-full layout to mimic full-screen chat UI
  if (!nowHidden){
    document.body.classList.add('chat-full');
  } else {
    document.body.classList.remove('chat-full');
  }
}

function msgCard(text, who, chip){
  const card = document.createElement('div');
  card.className = `msg-card ${who}`;
  if (chip){
    const c = document.createElement('div');
    c.className = 'msg-chip';
    c.textContent = chip;
    card.appendChild(c);
  }
  const body = document.createElement('div');
  body.className = 'msg-content';
  body.textContent = text;
  card.appendChild(body);
  const actions = document.createElement('div');
  actions.className = 'msg-actions';
  actions.innerHTML = `<button class="icon-lite" title="Regenerate" type="button">↻</button>
  <button class="icon-lite" title="Copy" type="button">⧉</button>
  <button class="icon-lite" title="Share" type="button">⤴</button>
  <span class="sep">·</span>
  <span class="time">just now</span>`;
  card.appendChild(actions);
  return card;
}

function ensureModernChatUI(){
  const chatBody = document.getElementById('chatBody');
  if (chatBody){
    // Replace default message if present
    chatBody.innerHTML = '';
    chatBody.appendChild(msgCard('Hi, I\u2019m Lyra. Drop a GLB to start.', 'ai', 'sad'));
  }
  const chatForm = document.getElementById('chatForm');
  if (chatForm){
    // Rebuild composer structure
    chatForm.classList.add('composer');
    chatForm.innerHTML = '';
    const attach = document.createElement('button');
    attach.type = 'button';
    attach.className = 'attach-btn';
    attach.title = 'Attach';
    attach.textContent = '📎';
    const input = document.createElement('input');
    input.id = 'chatText';
    input.type = 'text';
    input.placeholder = 'How can Lyra help?';
    input.autocomplete = 'off';
    const right = document.createElement('div');
    right.className = 'composer-right';
    const send = document.createElement('button');
    send.type = 'submit';
    send.className = 'send-icon';
    send.title = 'Send';
    send.textContent = '✈';
    const mic = document.createElement('button');
    mic.type = 'button';
    mic.className = 'mic-btn';
    mic.title = 'Voice';
    mic.innerHTML = '<span class="mic">≋</span>';
    right.appendChild(send);
    right.appendChild(mic);
    chatForm.appendChild(attach);
    chatForm.appendChild(input);
    chatForm.appendChild(right);
  }
  // Mode chip row
  const pane = document.getElementById('chatPane');
  if (pane && !document.getElementById('modeChips')){
    const chips = document.createElement('div');
    chips.id = 'modeChips';
    chips.className = 'mode-chips';
    chips.innerHTML = '<span class="chip"><span class="dot">●</span> Think Harder <button class="chip-x" type="button" aria-label="remove">×</button></span>';
    pane.insertBefore(chips, document.getElementById('chatForm'));
  }
}

// ---- Ready Player Me integration (iframe + postMessage) ----
function getRPMSubdomain(){
  try{
    const u = new URL(window.location.href);
    return u.searchParams.get('rpm') || 'demo';
  }catch{
    return 'demo';
  }
}

function buildCreatorUrl(){
  const sub = getRPMSubdomain();
  const params = new URLSearchParams({
    frameApi: '1',
    clearCache: '1',
    bodyType: 'fullbody',
    quickStart: '0',
    lang: 'en'
  });
  return `https://${sub}.readyplayer.me/avatar?${params.toString()}`;
}

function openReadyPlayerMe(){
  if (!rpmModalEl || !rpmFrameEl) return;
  rpmFrameEl.src = buildCreatorUrl();
  rpmModalEl.hidden = false;
}

function closeReadyPlayerMe(){
  if (!rpmModalEl || !rpmFrameEl) return;
  rpmModalEl.hidden = true;
  // Stop camera/mic on close by unloading src
  rpmFrameEl.src = 'about:blank';
  rpmSubscribed = false;
}

function setupReadyPlayerMeMessaging(){
  window.addEventListener('message', (event) => {
    const data = event.data;
    if (!data || data.source !== 'readyplayerme') return;

    // Subscribe to all events when the frame is ready
    if (data.eventName === 'v1.frame.ready' && rpmFrameEl && rpmFrameEl.contentWindow && !rpmSubscribed){
      rpmFrameEl.contentWindow.postMessage({
        target: 'readyplayerme',
        type: 'subscribe',
        eventName: 'v1.**'
      }, '*');
      rpmSubscribed = true;
    }

    if (data.eventName === 'v1.avatar.exported'){
      const url = data?.data?.url || '';
      if (url){
        // Load the exported GLB into the Three.js stage
        try { localStorage.setItem('rpmAvatarUrl', url); } catch {}
        loadModel(url).catch(()=>{});
        // Close the creator modal
        closeReadyPlayerMe();
      }
    }
  });
}
