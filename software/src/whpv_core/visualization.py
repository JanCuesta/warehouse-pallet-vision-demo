"""Reusable OpenCV rendering for warehouse driver-aware bounding boxes.

No ROS, Isaac Sim, order database, or YOLO runtime imports. Input frames are BGR.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import cv2
import numpy as np


RGB = tuple[int, int, int]
BGR = tuple[int, int, int]


@dataclass(frozen=True)
class DriverStyle:
    identifier: str
    color_rgb: RGB


@dataclass(frozen=True)
class OverlayDetection:
    label: str
    confidence: float
    bbox_xyxy: tuple[float, float, float, float]
    eligible_drivers: tuple[str, ...]


# Stable, deliberate colors for the three synthetic demo drivers.
DRIVER_STYLES: dict[str, DriverStyle] = {
    "Driver A": DriverStyle(identifier="D01", color_rgb=(59, 130, 246)),
    "Driver B": DriverStyle(identifier="D02", color_rgb=(22, 163, 74)),
    "Driver C": DriverStyle(identifier="D03", color_rgb=(225, 123, 22)),
}

SHARED_COLOR_RGB: RGB = (218, 177, 67)     # Gold border for >1 eligible driver
NO_ORDER_COLOR_RGB: RGB = (133, 139, 147)   # Gray when no eligible drivers
HEADER_COLOR_RGB: RGB = (48, 52, 60)        # Dark header like reference design
WHITE_RGB: RGB = (255, 255, 255)

# Only needed when the renderer receives an unfamiliar driver name.
_FALLBACK_PALETTE: tuple[RGB, ...] = (
    (16, 151, 191), (178, 81, 169), (119, 115, 216), (146, 112, 71),
)

_FONT = cv2.FONT_HERSHEY_SIMPLEX


def _bgr(rgb: RGB) -> BGR:
    return rgb[2], rgb[1], rgb[0]


def get_box_style(eligible_drivers: Sequence[str]) -> str:
    """Choose a visual style from unique eligible driver count."""
    count = len(set(eligible_drivers))
    if count == 0:
        return "no_order"
    if count == 1:
        return "single_driver"
    return "multiple_drivers"


def _driver_style(name: str, styles: Mapping[str, DriverStyle]) -> DriverStyle:
    if name in styles:
        return styles[name]
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    fallback = _FALLBACK_PALETTE[int.from_bytes(digest[:2], "big") % len(_FALLBACK_PALETTE)]
    # Explicit name snippet avoids confusing an unknown driver with a known ID.
    return DriverStyle(identifier=name[:7].upper(), color_rgb=fallback)


def _rounded_box(
    image: np.ndarray,
    p1: tuple[int, int],
    p2: tuple[int, int],
    color: BGR,
    radius: int = 6,
    thickness: int = -1,
) -> None:
    """OpenCV rounded rectangle: filled when thickness=-1, outlined otherwise."""
    x1, y1 = p1
    x2, y2 = p2
    if x2 <= x1 or y2 <= y1:
        return
    r = max(0, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
    if r == 0:
        cv2.rectangle(image, p1, p2, color, thickness, cv2.LINE_AA)
        return
    if thickness == -1:
        cv2.rectangle(image, (x1 + r, y1), (x2 - r, y2), color, -1)
        cv2.rectangle(image, (x1, y1 + r), (x2, y2 - r), color, -1)
        for xc, yc in (
            (x1 + r, y1 + r), (x2 - r, y1 + r),
            (x1 + r, y2 - r), (x2 - r, y2 - r),
        ):
            cv2.circle(image, (xc, yc), r, color, -1, cv2.LINE_AA)
    else:
        cv2.line(image, (x1 + r, y1), (x2 - r, y1), color, thickness, cv2.LINE_AA)
        cv2.line(image, (x1 + r, y2), (x2 - r, y2), color, thickness, cv2.LINE_AA)
        cv2.line(image, (x1, y1 + r), (x1, y2 - r), color, thickness, cv2.LINE_AA)
        cv2.line(image, (x2, y1 + r), (x2, y2 - r), color, thickness, cv2.LINE_AA)
        for center, start, end in (
            ((x1 + r, y1 + r), 180, 270),
            ((x2 - r, y1 + r), 270, 360),
            ((x2 - r, y2 - r), 0, 90),
            ((x1 + r, y2 - r), 90, 180),
        ):
            cv2.ellipse(image, center, (r, r), 0, start, end,
                        color, thickness, cv2.LINE_AA)


def _text_width(text: str, scale: float, thickness: int = 1) -> int:
    return cv2.getTextSize(text, _FONT, scale, thickness)[0][0]


def _fit_text(text: str, max_width: int, scale: float, thickness: int = 1) -> str:
    """Truncate long labels to avoid drawing over driver tags."""
    if max_width <= 0:
        return ""
    if _text_width(text, scale, thickness) <= max_width:
        return text
    suffix = "..."
    if _text_width(suffix, scale, thickness) > max_width:
        return ""
    for end in range(len(text) - 1, -1, -1):
        candidate = text[:end] + suffix
        if _text_width(candidate, scale, thickness) <= max_width:
            return candidate
    return suffix


def _draw_one(
    image: np.ndarray,
    detection: OverlayDetection,
    driver_styles: Mapping[str, DriverStyle],
    show_confidence: bool,
    max_driver_tags: int,
) -> None:
    height, width = image.shape[:2]
    corners = detection.bbox_xyxy
    if len(corners) != 4 or not all(math.isfinite(float(c)) for c in corners):
        return

    # Coordinates are expressed in pixels of the ORIGINAL source image.
    x1, y1, x2, y2 = (int(round(float(v))) for v in corners)
    x1, x2 = max(0, x1), min(width - 1, x2)
    y1, y2 = max(0, y1), min(height - 1, y2)
    if x2 <= x1 + 2 or y2 <= y1 + 2:
        return

    drivers = sorted(set(detection.eligible_drivers))
    mode = get_box_style(drivers)
    if mode == "no_order":
        border_rgb = NO_ORDER_COLOR_RGB
    elif mode == "single_driver":
        border_rgb = _driver_style(drivers[0], driver_styles).color_rgb
    else:
        border_rgb = SHARED_COLOR_RGB

    border_thickness = max(2, min(4, width // 260))
    _rounded_box(image, (x1, y1), (x2, y2),
                 _bgr(border_rgb), radius=7, thickness=border_thickness)

    # Calculate label and tags BEFORE choosing the dark header width.  A bbox
    # may be too narrow for "Orange 0.77" + D01/D02/D03 even though there is
    # ample space beside the bbox.  Extend the header locally when possible.
    header_h = 36 if height >= 160 else 25
    hy1 = y1 - header_h if y1 >= header_h else y1
    hy2 = hy1 + header_h
    tag_h = min(26, header_h - 8)
    tag_scale = 0.42 if height >= 160 else 0.33
    label_scale = 0.59 if height >= 160 else 0.41
    pad = 8
    gap = 4

    product = detection.label.replace("_", " ").strip().title() or "Unknown"
    preferred_label = (
        f"{product} {detection.confidence:.2f}"
        if show_confidence else product
    )

    if not drivers:
        full_tags: list[tuple[str, RGB]] = [("No order", NO_ORDER_COLOR_RGB)]
    else:
        full_tags = [
            (_driver_style(name, driver_styles).identifier,
             _driver_style(name, driver_styles).color_rgb)
            for name in drivers
        ]

    desired_count = min(len(full_tags), max(0, max_driver_tags))
    preview_tags = full_tags[:desired_count]
    hidden_count = len(full_tags) - desired_count
    if hidden_count:
        preview_tags = preview_tags + [(f"+{hidden_count}", NO_ORDER_COLOR_RGB)]
    preview_widths = [
        max(36, _text_width(text, tag_scale, 1) + 10)
        for text, _ in preview_tags
    ]
    preview_tags_width = sum(preview_widths) + gap * max(0, len(preview_widths) - 1)
    preferred_width = (
        2 * pad
        + _text_width(preferred_label, label_scale)
        + (preview_tags_width + 9 if preview_tags else 0)
    )

    bbox_width = x2 - x1
    # Prevent a very long product name from producing a huge header that
    # obscures another detection. Larger headings remain truncated if needed.
    local_limit = max(
        bbox_width,
        min(width - 1, bbox_width + 96, int(width * 0.55)),
    )
    header_width = min(width - 1, max(bbox_width, min(preferred_width, local_limit)))

    # Prefer left-aligned to bbox; shift left near the image's right edge.
    hx1 = min(x1, width - 1 - header_width)
    hx2 = hx1 + header_width
    _rounded_box(image, (hx1, hy1), (hx2, hy2),
                 _bgr(HEADER_COLOR_RGB), radius=6, thickness=-1)

    available_width = hx2 - hx1 - 2 * pad
    min_label_width = min(64, max(20, available_width // 4))
    tags: list[tuple[str, RGB]] = []
    for visible in range(desired_count, -1, -1):
        candidate = full_tags[:visible]
        hidden = len(full_tags) - visible
        if hidden:
            candidate = candidate + [(f"+{hidden}", NO_ORDER_COLOR_RGB)]
        widths = [max(36, _text_width(text, tag_scale, 1) + 10) for text, _ in candidate]
        used = sum(widths) + gap * max(0, len(widths) - 1)
        label_room = available_width - used - (9 if candidate else 0)
        if label_room >= min_label_width or visible == 0:
            tags = candidate
            break

    widths = [max(36, _text_width(t, tag_scale, 1) + 10) for t, _ in tags]
    if sum(widths) + gap * max(0, len(widths) - 1) > available_width - min_label_width:
        tags, widths = [], []
    tag_total = sum(widths) + gap * max(0, len(widths) - 1)
    label_max_width = max(0, available_width - tag_total - (9 if tags else 0))

    tag_right = hx2 - pad
    tag_y1 = hy1 + (header_h - tag_h) // 2
    tag_y2 = tag_y1 + tag_h
    for (tag_text, tag_rgb), tag_w in reversed(list(zip(tags, widths))):
        tag_left = tag_right - tag_w
        _rounded_box(image, (tag_left, tag_y1), (tag_right, tag_y2),
                     _bgr(tag_rgb), radius=5, thickness=-1)
        tw = _text_width(tag_text, tag_scale)
        tx = tag_left + (tag_w - tw) // 2
        ty = tag_y1 + (tag_h + cv2.getTextSize(tag_text, _FONT, tag_scale, 1)[0][1]) // 2 - 2
        cv2.putText(image, tag_text, (tx, ty), _FONT, tag_scale,
                    _bgr(WHITE_RGB), 1, cv2.LINE_AA)
        tag_right = tag_left - gap

    text = preferred_label if _text_width(preferred_label, label_scale) <= label_max_width else product
    text = _fit_text(text, label_max_width, label_scale)
    if text:
        baseline = hy1 + (header_h + cv2.getTextSize(text, _FONT, label_scale, 1)[0][1]) // 2 - 2
        cv2.putText(image, text, (hx1 + pad, baseline), _FONT, label_scale,
                    _bgr(WHITE_RGB), 1, cv2.LINE_AA)


def draw_overlay(
    image_bgr: np.ndarray,
    detections: Sequence[OverlayDetection],
    driver_styles: Mapping[str, DriverStyle] | None = None,
    *,
    show_confidence: bool = True,
    max_driver_tags: int = 3,
) -> np.ndarray:
    """Return a COPY of a BGR frame with driver-aware boxes and dark headers.

    Per detection:
    - 0 eligible drivers: gray box + No order tag
    - 1 eligible driver: driver's color + one driver tag
    - 2+ eligible drivers: gold box + per-driver colored tags (+N for overflow)

    This function neither selects a destination nor changes order progress.
    """
    if not isinstance(image_bgr, np.ndarray):
        raise TypeError("image_bgr must be a NumPy ndarray")
    if image_bgr.dtype != np.uint8 or image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ValueError("image_bgr must have shape (H, W, 3) and dtype uint8")
    if max_driver_tags < 0:
        raise ValueError("max_driver_tags must be nonnegative")

    result = image_bgr.copy()
    styles = DRIVER_STYLES if driver_styles is None else driver_styles
    for detection in detections:
        _draw_one(result, detection, styles, show_confidence, max_driver_tags)
    return result
