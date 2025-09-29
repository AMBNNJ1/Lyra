// Nova Chat: Ready Player Me + Three.js GLB viewer in the left pane
// No React required. Opens RPM Creator in an iframe and loads the exported GLB.

import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';
import { GLTFLoader } from 'https://unpkg.com/three@0.160.0/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'https://unpkg.com/three@0.160.0/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'https://unpkg.com/three@0.160.0/examples/jsm/environments/RoomEnvironment.js';

let renderer, scene, camera, controls;
let pmrem, envTex;
let avatarGroup = null;

let stageWrap, canvasEl;
let rpmModalEl, rpmFrameEl, rpmCloseBtn, rpmOpenBtn;
let rpmSubscribed = false;

init();
animate();

(async () => {
  try{
    const u = new URL(window.location.href);
    const m = u.searchParams.get('model');
    if (m) { await loadModel(m); return; }
    const saved = localStorage.getItem('rpmAvatarUrl');
    if (saved && await headExists(saved)) { await loadModel(saved); return; }
  }catch{}
})();

async function headExists(url){
  try{ const r = await fetch(url, { method:'HEAD', cache:'no-cache' }); return r.ok; }catch{ return false; }
}

function init(){
  stageWrap = document.querySelector('.unity-wrap');
  canvasEl = document.getElementById('unityCanvas');
  rpmModalEl = document.getElementById('rpmModal');
  rpmFrameEl = document.getElementById('rpmFrame');
  rpmCloseBtn = document.getElementById('rpmClose');
  rpmOpenBtn = document.getElementById('openAvatar');

  renderer = new THREE.WebGLRenderer({ canvas: canvasEl, antialias:true, alpha:true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  resize();

  scene = new THREE.Scene();

  camera = new THREE.PerspectiveCamera(40, canvasEl.clientWidth / canvasEl.clientHeight, 0.1, 100);
  camera.position.set(0.6, 1.2, 2.2);

  controls = new OrbitControls(camera, canvasEl);
  controls.enableDamping = true;
  controls.target.set(0, 1.3, 0);

  pmrem = new THREE.PMREMGenerator(renderer);
  envTex = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;
  scene.environment = envTex;
  scene.background = null;

  const hemi = new THREE.HemisphereLight(0xbfd3ff, 0x0b0f14, 0.6);
  scene.add(hemi);
  const dir = new THREE.DirectionalLight(0xffffff, 1.0);
  dir.position.set(2,4,2); dir.castShadow = true; dir.shadow.mapSize.set(2048,2048);
  scene.add(dir);

  const groundGeo = new THREE.PlaneGeometry(10,10);
  const groundMat = new THREE.ShadowMaterial({ opacity:0.2 });
  const ground = new THREE.Mesh(groundGeo, groundMat);
  ground.rotation.x = -Math.PI/2; ground.position.y = 0; ground.receiveShadow = true;
  scene.add(ground);

  window.addEventListener('resize', resize);

  if (rpmOpenBtn) rpmOpenBtn.addEventListener('click', () => openReadyPlayerMe());
  if (rpmCloseBtn) rpmCloseBtn.addEventListener('click', () => closeReadyPlayerMe());
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !rpmModalEl.hidden) closeReadyPlayerMe(); });

  setupReadyPlayerMeMessaging();
}

function animate(){ requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); }

function resize(){
  const rect = canvasEl.getBoundingClientRect();
  const w = Math.max(100, rect.width);
  const h = Math.max(100, rect.height);
  renderer.setSize(w, h, false);
  camera.aspect = w / h; camera.updateProjectionMatrix();
}

async function loadModel(url){
  const loader = new GLTFLoader();
  const gltf = await loader.loadAsync(url);
  if (avatarGroup){
    scene.remove(avatarGroup);
    avatarGroup.traverse(obj => {
      if (obj.isMesh){ obj.geometry?.dispose(); obj.material?.dispose?.(); }
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
      obj.castShadow = true; obj.receiveShadow = false;
      if (obj.material && obj.material.isMeshStandardMaterial) obj.material.envMapIntensity = 1.0;
    }
  });
}

function recenterCamera(){
  if (!avatarGroup) return;
  const box = new THREE.Box3().setFromObject(avatarGroup);
  const size = new THREE.Vector3(); box.getSize(size);
  const center = new THREE.Vector3(); box.getCenter(center);
  avatarGroup.position.sub(center);
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const radius = sphere.radius || 1.0;
  const height = size.y || 1.8;
  const desiredY = Math.min(Math.max(height * 0.65, 1.2), 2.2);
  const dist = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov*0.5));
  const targetDist = THREE.MathUtils.clamp(dist * 1.2, 1.2, 6.5);
  controls.target.set(0, desiredY, 0);
  camera.position.set(targetDist*0.3, desiredY + targetDist*0.25, targetDist);
  controls.update();
}

// -------- Ready Player Me: iframe + postMessage --------
function getRPMSubdomain(){
  try { const u = new URL(window.location.href); return u.searchParams.get('rpm') || 'demo'; } catch { return 'demo'; }
}

function buildCreatorUrl(){
  const sub = getRPMSubdomain();
  const params = new URLSearchParams({ frameApi:'1', clearCache:'1', bodyType:'fullbody', quickStart:'0', lang:'en' });
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
  rpmFrameEl.src = 'about:blank';
  rpmSubscribed = false;
}

function setupReadyPlayerMeMessaging(){
  window.addEventListener('message', (event) => {
    const data = event.data;
    if (!data || data.source !== 'readyplayerme') return;

    if (data.eventName === 'v1.frame.ready' && rpmFrameEl && rpmFrameEl.contentWindow && !rpmSubscribed){
      rpmFrameEl.contentWindow.postMessage({ target:'readyplayerme', type:'subscribe', eventName:'v1.**' }, '*');
      rpmSubscribed = true;
    }

    if (data.eventName === 'v1.avatar.exported'){
      const url = data?.data?.url || '';
      if (url){
        try { localStorage.setItem('rpmAvatarUrl', url); } catch {}
        loadModel(url).catch(()=>{});
        closeReadyPlayerMe();
      }
    }
  });
}

