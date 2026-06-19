export type TrackerState = 'idle' | 'tracking' | 'searching' | 'lost';

export interface BBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ApiInfo {
  local_url: string;
  public_url: string | null;
  websocket_url: string | null;
}

export interface ServerMessage {
  type: 'status' | 'frame' | 'bbox' | 'lost' | 'error';
  status?: TrackerState;
  bbox?: BBox;
  message?: string;
  ok?: boolean;
  reacquired?: boolean;
}
