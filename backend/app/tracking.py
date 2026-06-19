from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

BBox = tuple[int, int, int, int]


def decode_jpeg(payload: bytes) -> np.ndarray | None:
    encoded_frame = np.frombuffer(payload, dtype=np.uint8)
    if encoded_frame.size == 0:
        return None

    return cv2.imdecode(encoded_frame, cv2.IMREAD_COLOR)


def parse_bbox(payload: object, frame: np.ndarray) -> BBox | None:
    if not isinstance(payload, dict):
        return None

    values = [payload.get(key) for key in ("x", "y", "w", "h")]
    if not all(isinstance(value, (int, float)) for value in values):
        return None

    x, y, width, height = (int(value) for value in values)
    frame_height, frame_width = frame.shape[:2]

    x = max(0, min(x, frame_width - 1))
    y = max(0, min(y, frame_height - 1))
    width = min(width, frame_width - x)
    height = min(height, frame_height - y)

    if width < 2 or height < 2:
        return None

    return x, y, width, height


@dataclass
class TrackingSession:
    frame: np.ndarray | None = None
    tracker: Any | None = None
    state: str = "idle"

    def receive_frame(self, payload: bytes) -> dict[str, object] | None:
        frame = decode_jpeg(payload)
        if frame is None:
            return {"type": "error", "message": "Invalid JPEG frame"}

        self.frame = frame
        if self.tracker is None:
            return {"type": "frame", "ok": True, "status": self.state}

        ok, bbox = self.tracker.update(frame)
        if not ok:
            self.tracker = None
            self.state = "lost"
            return {"type": "lost", "ok": False}

        x, y, width, height = (round(value) for value in bbox)
        return {
            "type": "bbox",
            "bbox": {"x": x, "y": y, "w": width, "h": height},
            "ok": True,
        }

    def select(self, payload: object) -> dict[str, object]:
        if self.frame is None:
            return {
                "type": "error",
                "message": "Send a JPEG frame before selecting an object",
            }

        bbox = parse_bbox(payload, self.frame)
        if bbox is None:
            return {"type": "error", "message": "Invalid bounding box"}

        tracker = cv2.TrackerCSRT_create()
        initialized = tracker.init(self.frame, bbox)
        if initialized is False:
            return {"type": "error", "message": "Tracker initialization failed"}

        self.tracker = tracker
        self.state = "tracking"
        return {"type": "status", "status": self.state}
