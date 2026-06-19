from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

BBox = tuple[int, int, int, int]

SEARCH_SCALES = (0.6, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5)
MATCH_THRESHOLD = 0.76
REACQUIRE_CONFIRMATIONS = 3
TRACKING_MISMATCH_LIMIT = 3
MIN_COLOR_SIMILARITY = 0.45
MIN_TRACKING_COLOR_SIMILARITY = 0.35
MIN_TRACKING_STRUCTURE_SIMILARITY = 0.35
MIN_ORB_FEATURES = 6
MIN_ORB_MATCH_RATIO = 0.06


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


def crop_frame(frame: np.ndarray, bbox: BBox) -> np.ndarray | None:
    x, y, width, height = bbox
    frame_height, frame_width = frame.shape[:2]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(frame_width, x + width)
    y2 = min(frame_height, y + height)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return frame[y1:y2, x1:x2].copy()


def boxes_are_near(first: BBox, second: BBox) -> bool:
    first_center = (first[0] + first[2] / 2, first[1] + first[3] / 2)
    second_center = (second[0] + second[2] / 2, second[1] + second[3] / 2)
    distance = np.hypot(
        first_center[0] - second_center[0],
        first_center[1] - second_center[1],
    )
    return distance <= max(first[2], first[3], second[2], second[3]) * 1.5


def color_similarity(reference: np.ndarray, candidate: np.ndarray) -> float:
    reference_hsv = cv2.cvtColor(reference, cv2.COLOR_BGR2HSV)
    candidate_hsv = cv2.cvtColor(candidate, cv2.COLOR_BGR2HSV)
    reference_hist = cv2.calcHist(
        [reference_hsv], [0, 1], None, [24, 16], [0, 180, 0, 256]
    )
    candidate_hist = cv2.calcHist(
        [candidate_hsv], [0, 1], None, [24, 16], [0, 180, 0, 256]
    )
    cv2.normalize(reference_hist, reference_hist)
    cv2.normalize(candidate_hist, candidate_hist)
    return float(
        cv2.compareHist(reference_hist, candidate_hist, cv2.HISTCMP_CORREL)
    )


def structure_similarity(reference: np.ndarray, candidate: np.ndarray) -> float:
    size = (reference.shape[1], reference.shape[0])
    resized_candidate = cv2.resize(candidate, size)
    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    candidate_gray = cv2.cvtColor(resized_candidate, cv2.COLOR_BGR2GRAY)
    return float(
        cv2.matchTemplate(
            candidate_gray, reference_gray, cv2.TM_CCOEFF_NORMED
        )[0, 0]
    )


def orb_features(
    image: np.ndarray,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    keypoints, descriptors = cv2.ORB_create(
        nfeatures=300,
        edgeThreshold=5,
        patchSize=15,
        fastThreshold=10,
    ).detectAndCompute(gray, None)
    if not keypoints or descriptors is None:
        return None, None
    points = np.float32([keypoint.pt for keypoint in keypoints])
    return points, descriptors


def orb_descriptors(image: np.ndarray) -> np.ndarray | None:
    _points, descriptors = orb_features(image)
    return descriptors


def orb_match_ratio(
    reference_descriptors: np.ndarray,
    candidate: np.ndarray,
) -> float:
    candidate_descriptors = orb_descriptors(candidate)
    if (
        candidate_descriptors is None
        or len(candidate_descriptors) < MIN_ORB_FEATURES
    ):
        return 0.0

    matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(
        reference_descriptors, candidate_descriptors, k=2
    )
    good_matches = [
        first
        for pair in matches
        if len(pair) == 2
        for first, second in [pair]
        if first.distance < 0.75 * second.distance
    ]
    return len(good_matches) / max(
        1, min(len(reference_descriptors), len(candidate_descriptors))
    )


@dataclass
class TrackingSession:
    frame: np.ndarray | None = None
    tracker: Any | None = None
    state: str = "idle"
    reference_template: np.ndarray | None = None
    reference_points: np.ndarray | None = None
    reference_descriptors: np.ndarray | None = None
    last_bbox: BBox | None = None
    candidate_bbox: BBox | None = None
    candidate_confirmations: int = 0
    tracking_mismatches: int = 0

    def receive_frame(self, payload: bytes) -> dict[str, object] | None:
        frame = decode_jpeg(payload)
        if frame is None:
            return {"type": "error", "message": "Invalid JPEG frame"}

        self.frame = frame
        if self.tracker is None:
            if self.state == "searching":
                return self._search_for_object(frame)
            return {"type": "frame", "ok": True, "status": self.state}

        ok, bbox = self.tracker.update(frame)
        if not ok:
            self.tracker = None
            self.state = "searching"
            return self._search_for_object(frame)

        x, y, width, height = (round(value) for value in bbox)
        self.last_bbox = (x, y, width, height)
        tracked_crop = crop_frame(frame, self.last_bbox)
        if tracked_crop is None or not self._appearance_matches(tracked_crop):
            self.tracking_mismatches += 1
        else:
            self.tracking_mismatches = 0

        if self.tracking_mismatches >= TRACKING_MISMATCH_LIMIT:
            self.tracker = None
            self.state = "searching"
            self.candidate_bbox = None
            self.candidate_confirmations = 0
            return self._search_for_object(frame)

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
        template = crop_frame(self.frame, bbox)
        self.reference_template = template
        if template is not None:
            self.reference_points, self.reference_descriptors = orb_features(
                template
            )
        else:
            self.reference_points = None
            self.reference_descriptors = None
        self.last_bbox = bbox
        self.candidate_bbox = None
        self.candidate_confirmations = 0
        self.tracking_mismatches = 0
        return {"type": "status", "status": self.state}

    def _search_for_object(self, frame: np.ndarray) -> dict[str, object]:
        match = self._best_match(frame)
        if match is None:
            self.candidate_bbox = None
            self.candidate_confirmations = 0
            return {"type": "frame", "ok": True, "status": "searching"}

        bbox, _score = match
        if self.candidate_bbox is not None and boxes_are_near(
            self.candidate_bbox, bbox
        ):
            self.candidate_confirmations += 1
        else:
            self.candidate_bbox = bbox
            self.candidate_confirmations = 1

        self.candidate_bbox = bbox
        if self.candidate_confirmations < REACQUIRE_CONFIRMATIONS:
            return {"type": "frame", "ok": True, "status": "searching"}

        tracker = cv2.TrackerCSRT_create()
        initialized = tracker.init(frame, bbox)
        if initialized is False:
            self.candidate_bbox = None
            self.candidate_confirmations = 0
            return {"type": "frame", "ok": True, "status": "searching"}

        self.tracker = tracker
        self.state = "tracking"
        self.last_bbox = bbox
        self.candidate_bbox = None
        self.candidate_confirmations = 0
        self.tracking_mismatches = 0
        return {
            "type": "bbox",
            "bbox": {"x": bbox[0], "y": bbox[1], "w": bbox[2], "h": bbox[3]},
            "ok": True,
            "reacquired": True,
        }

    def _best_match(self, frame: np.ndarray) -> tuple[BBox, float] | None:
        if self.reference_template is None:
            return None

        feature_match = self._best_orb_match(frame)
        if feature_match is not None:
            return feature_match

        best: tuple[BBox, float] | None = None

        for scale in SEARCH_SCALES:
            width = max(2, round(self.reference_template.shape[1] * scale))
            height = max(2, round(self.reference_template.shape[0] * scale))
            if width > frame.shape[1] or height > frame.shape[0]:
                continue

            resized = cv2.resize(self.reference_template, (width, height))
            result = cv2.matchTemplate(frame, resized, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            bbox = (location[0], location[1], width, height)
            if best is None or score > best[1]:
                best = (bbox, score)

        if best is None or best[1] < MATCH_THRESHOLD:
            return None
        candidate = crop_frame(frame, best[0])
        if candidate is None or not self._appearance_matches(
            candidate, reacquiring=True
        ):
            return None
        return best

    def _best_orb_match(self, frame: np.ndarray) -> tuple[BBox, float] | None:
        reference_points = self.reference_points
        reference_descriptors = self.reference_descriptors
        if (
            self.reference_template is None
            or reference_points is None
            or reference_descriptors is None
            or len(reference_descriptors) < MIN_ORB_FEATURES
        ):
            return None

        frame_points, frame_descriptors = orb_features(frame)
        if (
            frame_points is None
            or frame_descriptors is None
            or len(frame_descriptors) < MIN_ORB_FEATURES
        ):
            return None

        matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(
            reference_descriptors, frame_descriptors, k=2
        )
        good_matches = [
            first
            for pair in matches
            if len(pair) == 2
            for first, second in [pair]
            if first.distance < 0.75 * second.distance
        ]
        if len(good_matches) < MIN_ORB_FEATURES:
            return None

        source = np.float32(
            [reference_points[match.queryIdx] for match in good_matches]
        ).reshape(-1, 1, 2)
        destination = np.float32(
            [frame_points[match.trainIdx] for match in good_matches]
        ).reshape(-1, 1, 2)
        homography, inlier_mask = cv2.findHomography(
            source, destination, cv2.RANSAC, 5.0
        )
        if homography is None or inlier_mask is None:
            return None

        inlier_ratio = float(inlier_mask.sum()) / len(good_matches)
        if int(inlier_mask.sum()) < MIN_ORB_FEATURES or inlier_ratio < 0.5:
            return None

        height, width = self.reference_template.shape[:2]
        corners = np.float32(
            [[0, 0], [width, 0], [width, height], [0, height]]
        ).reshape(-1, 1, 2)
        transformed = cv2.perspectiveTransform(corners, homography)
        if not np.isfinite(transformed).all():
            return None

        x, y, matched_width, matched_height = cv2.boundingRect(transformed)
        bbox = parse_bbox(
            {"x": x, "y": y, "w": matched_width, "h": matched_height},
            frame,
        )
        if bbox is None:
            return None

        area_ratio = (bbox[2] * bbox[3]) / (width * height)
        if area_ratio < 0.25 or area_ratio > 4.0:
            return None
        return bbox, inlier_ratio

    def _appearance_matches(
        self,
        candidate: np.ndarray,
        *,
        reacquiring: bool = False,
    ) -> bool:
        if self.reference_template is None:
            return False

        color_score = color_similarity(self.reference_template, candidate)
        structure_score = structure_similarity(self.reference_template, candidate)
        if reacquiring:
            if color_score < MIN_COLOR_SIMILARITY:
                return False
        elif (
            color_score < MIN_TRACKING_COLOR_SIMILARITY
            or structure_score < MIN_TRACKING_STRUCTURE_SIMILARITY
        ):
            return False

        descriptors = self.reference_descriptors
        if descriptors is None or len(descriptors) < MIN_ORB_FEATURES:
            return True
        return orb_match_ratio(descriptors, candidate) >= MIN_ORB_MATCH_RATIO
