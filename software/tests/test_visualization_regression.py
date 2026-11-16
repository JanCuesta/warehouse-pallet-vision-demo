"""Regression tests for confidence labels and tricky bounding-box layouts."""

import cv2
import numpy as np
import pytest

from whpv_core.visualization import (
    DRIVER_STYLES, HEADER_COLOR_RGB, OverlayDetection, draw_overlay,
)


def _det(label, drivers, box, confidence=0.77):
    return OverlayDetection(
        label=label, confidence=confidence,
        bbox_xyxy=box, eligible_drivers=tuple(drivers),
    )


@pytest.fixture
def text_spy(monkeypatch):
    """Observe OpenCV draw text without unreliable OCR or font-pixel tests."""
    texts = []
    real_put_text = cv2.putText

    def record(*args, **kwargs):
        texts.append(args[1])
        return real_put_text(*args, **kwargs)

    monkeypatch.setattr(cv2, "putText", record)
    return texts


def test_orange_shows_confidence_with_three_driver_tags(text_spy):
    # Dimensions approximate the narrow orange boxes in the user's screenshot.
    frame = np.full((563, 780, 3), 242, dtype=np.uint8)
    result = draw_overlay(frame, [
        _det("orange", ["Driver A", "Driver B", "Driver C"],
             (487, 104, 721, 266), 0.768),
    ])
    assert "Orange 0.77" in text_spy
    for tag in ("D01", "D02", "D03"):
        assert tag in text_spy
    assert result.shape == frame.shape
    assert np.array_equal(frame, np.full_like(frame, 242))


def test_right_edge_header_shifts_inward_without_losing_confidence(text_spy):
    frame = np.full((563, 780, 3), 225, dtype=np.uint8)
    draw_overlay(frame, [
        _det("orange", ["Driver A", "Driver B", "Driver C"],
             (600, 120, 779, 265)),
    ])
    assert "Orange 0.77" in text_spy
    assert {"D01", "D02", "D03"}.issubset(text_spy)


def test_all_three_styles_and_confidence_labels(text_spy):
    frame = np.full((720, 1280, 3), 239, dtype=np.uint8)
    draw_overlay(frame, [
        _det("apple", ["Driver A"], (50, 90, 340, 350), 0.92),
        _det("banana", ["Driver B", "Driver C"], (460, 90, 780, 350), 0.95),
        _det("orange", [], (910, 90, 1190, 350), 0.74),
    ])
    assert {"Apple 0.92", "Banana 0.95", "Orange 0.74", "No order"}.issubset(text_spy)
    assert {"D01", "D02", "D03"}.issubset(text_spy)


def test_duplicate_driver_names_draw_only_one_tag(text_spy):
    frame = np.full((300, 500, 3), 240, dtype=np.uint8)
    draw_overlay(frame, [
        _det("apple", ["Driver A", "Driver A"], (100, 80, 350, 230)),
    ])
    assert text_spy.count("D01") == 1
    assert "Apple 0.77" in text_spy


def test_can_hide_confidence_by_configuration(text_spy):
    frame = np.full((300, 500, 3), 240, dtype=np.uint8)
    draw_overlay(frame, [
        _det("apple", ["Driver A"], (100, 80, 350, 230)),
    ], show_confidence=False)
    assert "Apple" in text_spy
    assert "Apple 0.77" not in text_spy


def test_tiny_frame_and_long_name_do_not_crash():
    frame = np.full((100, 120, 3), 200, dtype=np.uint8)
    result = draw_overlay(frame, [
        _det("extremely_long_product_name", ["Driver A", "Driver B", "Driver C"],
             (5, 5, 100, 90)),
    ])
    assert result.shape == frame.shape
