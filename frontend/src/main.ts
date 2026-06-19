import './style.css';
import { TrackingConnection } from './trackingConnection';
import type { ApiInfo, BBox, ServerMessage, TrackerState } from './types';

const app = document.querySelector<HTMLDivElement>('#app');

if (!app) {
  throw new Error('Application root was not found');
}

app.innerHTML = `
  <main class="page-shell">
    <header class="hero">
      <p class="eyebrow">OpenCV CSRT demo</p>
      <h1>Browser Object Tracking</h1>
      <p class="intro">Open the camera, then drag a rectangle around an object.</p>
    </header>

    <section class="status-grid" aria-label="Connection information">
      <article class="status-card">
        <span>Backend</span>
        <strong id="backend-status" data-state="pending">Checking...</strong>
      </article>
      <article class="status-card">
        <span>Ngrok</span>
        <strong id="ngrok-status" data-state="pending">Checking...</strong>
      </article>
      <article class="status-card">
        <span>Tracker</span>
        <strong id="tracker-status" data-state="idle">Idle</strong>
      </article>
      <article class="status-card">
        <span>Throughput</span>
        <strong id="fps-status" data-state="idle">0.0 FPS</strong>
      </article>
    </section>

    <section class="camera-card">
      <div id="camera-stage" class="camera-stage">
        <video id="camera" autoplay muted playsinline></video>
        <canvas id="overlay"></canvas>
        <div id="camera-placeholder" class="camera-placeholder">
          Camera preview will appear here
        </div>
      </div>

      <div class="camera-actions">
        <button id="open-camera" type="button">Open Camera</button>
        <p id="message" role="status">Camera is closed.</p>
      </div>
    </section>

    <section class="connection-card">
      <h2>Connection</h2>
      <dl>
        <div><dt>Local</dt><dd id="local-url">Unavailable</dd></div>
        <div><dt>Public</dt><dd id="public-url">Unavailable</dd></div>
        <div><dt>WebSocket</dt><dd id="websocket-url">Unavailable</dd></div>
      </dl>
    </section>
  </main>
`;

const video = getElement<HTMLVideoElement>('camera');
const overlay = getElement<HTMLCanvasElement>('overlay');
const cameraStage = getElement<HTMLDivElement>('camera-stage');
const openCameraButton = getElement<HTMLButtonElement>('open-camera');
const placeholder = getElement<HTMLDivElement>('camera-placeholder');
const message = getElement<HTMLParagraphElement>('message');
const backendStatus = getElement<HTMLElement>('backend-status');
const ngrokStatus = getElement<HTMLElement>('ngrok-status');
const trackerStatus = getElement<HTMLElement>('tracker-status');
const fpsStatus = getElement<HTMLElement>('fps-status');
const localUrl = getElement<HTMLElement>('local-url');
const publicUrl = getElement<HTMLElement>('public-url');
const websocketUrl = getElement<HTMLElement>('websocket-url');
const overlayContext = getCanvasContext(overlay);

let selectionStart: { x: number; y: number } | null = null;
let selectionBox: BBox | null = null;
let trackedBox: BBox | null = null;
let trackerState: TrackerState = 'idle';
let processedFrameTimes: number[] = [];
const connection = new TrackingConnection({
  video,
  onMessage: handleServerMessage,
  onFrameProcessed: recordProcessedFrame,
  onInvalidMessage: () => {
    message.textContent = 'Backend sent an invalid response.';
  },
  onClose: () => {
    message.textContent = 'Tracking connection closed.';
    setTrackerState('idle');
    resetFps();
  },
});

function getElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`Missing element: ${id}`);
  }
  return element as T;
}

function getCanvasContext(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const context = canvas.getContext('2d');
  if (!context) {
    throw new Error('Canvas is not supported by this browser');
  }
  return context;
}

function setServiceStatus(
  element: HTMLElement,
  label: string,
  state: 'online' | 'offline' | 'pending',
): void {
  element.textContent = label;
  element.dataset.state = state;
}

function setTrackerState(state: TrackerState): void {
  trackerState = state;
  trackerStatus.textContent = state[0].toUpperCase() + state.slice(1);
  trackerStatus.dataset.state = state;
  drawOverlay();
}

function recordProcessedFrame(): void {
  processedFrameTimes.push(performance.now());
  updateFps();
}

function updateFps(): void {
  const now = performance.now();
  processedFrameTimes = processedFrameTimes.filter(
    (timestamp) => timestamp >= now - 3000,
  );

  const measurementDuration =
    processedFrameTimes.length > 1
      ? processedFrameTimes.at(-1)! - processedFrameTimes[0]
      : 0;
  const fps =
    measurementDuration > 0
      ? ((processedFrameTimes.length - 1) * 1000) / measurementDuration
      : 0;

  fpsStatus.textContent = `${fps.toFixed(1)} FPS`;
  fpsStatus.dataset.state = fps > 0 ? 'online' : 'idle';
}

function resetFps(): void {
  processedFrameTimes = [];
  updateFps();
}

async function loadApiInfo(): Promise<void> {
  try {
    const response = await fetch('/api/info');
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }

    const info = (await response.json()) as ApiInfo;
    localUrl.textContent = info.local_url;
    publicUrl.textContent = info.public_url ?? 'Not connected';
    websocketUrl.textContent = info.websocket_url ?? 'Not connected';
    setServiceStatus(backendStatus, 'Online', 'online');
    setServiceStatus(
      ngrokStatus,
      info.public_url ? 'Connected' : 'Disconnected',
      info.public_url ? 'online' : 'offline',
    );
  } catch {
    setServiceStatus(backendStatus, 'Offline', 'offline');
    setServiceStatus(ngrokStatus, 'Unavailable', 'offline');
  }
}

function handleServerMessage(payload: ServerMessage): void {
  if (payload.type === 'bbox' && payload.bbox) {
    trackedBox = payload.bbox;
    setTrackerState('tracking');
    return;
  }

  if (payload.type === 'lost') {
    trackedBox = null;
    setTrackerState('lost');
    message.textContent = 'Object lost. Drag a new rectangle to try again.';
    return;
  }

  if (payload.type === 'frame') {
    return;
  }

  if (payload.type === 'status' && payload.status) {
    setTrackerState(payload.status);
    message.textContent =
      payload.status === 'tracking' ? 'Tracking object.' : 'Select an object.';
    return;
  }

  if (payload.type === 'error') {
    message.textContent = payload.message ?? 'Tracking error.';
  }
}

async function openCamera(): Promise<void> {
  openCameraButton.disabled = true;
  message.textContent = 'Requesting camera access...';

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: 'environment' } },
    });

    video.srcObject = stream;
    await video.play();
    resizeCanvases();
    await connection.connect();

    placeholder.hidden = true;
    cameraStage.classList.add('has-camera');
    overlay.classList.add('is-active');
    message.textContent = 'Drag a rectangle around an object.';
    resetFps();
    connection.startFramePipeline();
  } catch (error) {
    stopCamera();
    openCameraButton.disabled = false;
    message.textContent =
      error instanceof Error ? error.message : 'Could not open camera.';
  }
}

function resizeCanvases(): void {
  overlay.width = video.videoWidth;
  overlay.height = video.videoHeight;
  connection.resizeFrameCanvas();
}

function stopCamera(): void {
  connection.stopFramePipeline();
  resetFps();
  const stream = video.srcObject;
  if (stream instanceof MediaStream) {
    stream.getTracks().forEach((track) => track.stop());
  }
  video.srcObject = null;
  cameraStage.classList.remove('has-camera');
  connection.close();
}

function pointerPosition(event: PointerEvent): { x: number; y: number } {
  const bounds = overlay.getBoundingClientRect();
  return {
    x: Math.round(((event.clientX - bounds.left) / bounds.width) * overlay.width),
    y: Math.round(((event.clientY - bounds.top) / bounds.height) * overlay.height),
  };
}

function boxFromPoints(
  start: { x: number; y: number },
  end: { x: number; y: number },
): BBox {
  return {
    x: Math.min(start.x, end.x),
    y: Math.min(start.y, end.y),
    w: Math.abs(end.x - start.x),
    h: Math.abs(end.y - start.y),
  };
}

function drawOverlay(): void {
  overlayContext.clearRect(0, 0, overlay.width, overlay.height);
  const box = selectionBox ?? trackedBox;
  if (!box) {
    return;
  }

  overlayContext.lineWidth = Math.max(3, overlay.width / 240);
  overlayContext.strokeStyle = trackerState === 'lost' ? '#ef4444' : '#22c55e';
  overlayContext.fillStyle = 'rgba(34, 197, 94, 0.12)';
  overlayContext.fillRect(box.x, box.y, box.w, box.h);
  overlayContext.strokeRect(box.x, box.y, box.w, box.h);
}

overlay.addEventListener('pointerdown', (event) => {
  if (!connection.isOpen) {
    return;
  }
  overlay.setPointerCapture(event.pointerId);
  selectionStart = pointerPosition(event);
  selectionBox = { ...selectionStart, w: 0, h: 0 };
  trackedBox = null;
  setTrackerState('idle');
});

overlay.addEventListener('pointermove', (event) => {
  if (!selectionStart) {
    return;
  }
  selectionBox = boxFromPoints(selectionStart, pointerPosition(event));
  drawOverlay();
});

overlay.addEventListener('pointerup', (event) => {
  if (!selectionStart || !selectionBox || !connection.isOpen) {
    return;
  }

  overlay.releasePointerCapture(event.pointerId);
  const bbox = selectionBox;
  selectionStart = null;
  selectionBox = null;

  if (bbox.w < 2 || bbox.h < 2) {
    message.textContent = 'Selection is too small.';
    drawOverlay();
    return;
  }

  trackedBox = bbox;
  connection.sendSelect(bbox);
  message.textContent = 'Initializing tracker...';
  drawOverlay();
});

openCameraButton.addEventListener('click', () => void openCamera());
window.addEventListener('beforeunload', stopCamera);

void loadApiInfo();
window.setInterval(() => void loadApiInfo(), 5000);
window.setInterval(updateFps, 500);
