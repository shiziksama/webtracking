import type { BBox, ServerMessage } from './types';

interface TrackingConnectionOptions {
  video: HTMLVideoElement;
  onMessage: (payload: ServerMessage) => void;
  onFrameProcessed: () => void;
  onInvalidMessage: () => void;
  onClose: () => void;
}

function currentWebSocketUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/track`;
}

function isFrameResponse(payload: ServerMessage): boolean {
  return payload.type === 'frame' || payload.type === 'bbox' || payload.type === 'lost';
}

export class TrackingConnection {
  private readonly video: HTMLVideoElement;
  private readonly onMessage: (payload: ServerMessage) => void;
  private readonly onFrameProcessed: () => void;
  private readonly onInvalidMessage: () => void;
  private readonly onClose: () => void;
  private readonly frameCanvas = document.createElement('canvas');
  private readonly frameContext: CanvasRenderingContext2D;
  private socket: WebSocket | null = null;
  private framePipelineActive = false;
  private frameInFlight = false;

  constructor(options: TrackingConnectionOptions) {
    this.video = options.video;
    this.onMessage = options.onMessage;
    this.onFrameProcessed = options.onFrameProcessed;
    this.onInvalidMessage = options.onInvalidMessage;
    this.onClose = options.onClose;

    const context = this.frameCanvas.getContext('2d');
    if (!context) {
      throw new Error('Canvas is not supported by this browser');
    }
    this.frameContext = context;
  }

  get isOpen(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.socket = new WebSocket(currentWebSocketUrl());

      this.socket.addEventListener('open', () => resolve(), { once: true });
      this.socket.addEventListener(
        'error',
        () => reject(new Error('WebSocket failed')),
        { once: true },
      );
      this.socket.addEventListener('message', (event: MessageEvent<string>) =>
        this.handleServerMessage(event),
      );
      this.socket.addEventListener('close', () => {
        this.stopFramePipeline();
        this.onClose();
      });
    });
  }

  resizeFrameCanvas(): void {
    this.frameCanvas.width = this.video.videoWidth;
    this.frameCanvas.height = this.video.videoHeight;
  }

  startFramePipeline(): void {
    this.stopFramePipeline();
    this.framePipelineActive = true;
    void this.sendFrame();
  }

  stopFramePipeline(): void {
    this.framePipelineActive = false;
    this.frameInFlight = false;
  }

  sendSelect(bbox: BBox): void {
    this.socket?.send(JSON.stringify({ type: 'select', bbox }));
  }

  close(): void {
    this.stopFramePipeline();
    this.socket?.close();
    this.socket = null;
  }

  private handleServerMessage(event: MessageEvent<string>): void {
    let payload: ServerMessage;
    try {
      payload = JSON.parse(event.data) as ServerMessage;
    } catch {
      this.onInvalidMessage();
      this.sendNextFrame(this.frameInFlight);
      return;
    }

    this.onMessage(payload);
    if (isFrameResponse(payload)) {
      this.onFrameProcessed();
    }
    this.sendNextFrame(isFrameResponse(payload) || this.isFrameError(payload));
  }

  private isFrameError(payload: ServerMessage): boolean {
    return payload.type === 'error' && this.frameInFlight;
  }

  private async sendFrame(): Promise<void> {
    if (
      !this.framePipelineActive ||
      this.frameInFlight ||
      !this.isOpen ||
      this.video.readyState < 2
    ) {
      return;
    }

    this.frameInFlight = true;
    this.frameContext.drawImage(
      this.video,
      0,
      0,
      this.frameCanvas.width,
      this.frameCanvas.height,
    );
    const jpeg = await new Promise<Blob | null>((resolve) =>
      this.frameCanvas.toBlob(resolve, 'image/jpeg', 0.72),
    );

    if (jpeg && this.isOpen) {
      this.socket?.send(jpeg);
      return;
    }

    this.frameInFlight = false;
  }

  private sendNextFrame(previousFrameCompleted = false): void {
    if (previousFrameCompleted) {
      this.frameInFlight = false;
    }

    if (!this.framePipelineActive) {
      return;
    }

    window.requestAnimationFrame(() => void this.sendFrame());
  }
}
