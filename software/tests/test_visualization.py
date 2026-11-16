"""Stand-alone rendering tests: no Isaac Sim and no ROS environment needed."""

import cv2
import numpy as np
import pytest

from whpv_core.visualization import (
    DRIVER_STYLES,
    HEADER_COLOR_RGB,
    NO_ORDER_COLOR_RGB,
    SHARED_COLOR_RGB,
    OverlayDetection,
    draw_overlay,
    get_box_style,
)


def _image():
    return np.full((300, 440, 3), 225, dtype=np.uint8)


def _det(drivers, label="apple", bbox=(55, 90, 370, 255)):
    return OverlayDetection(
        label=label, confidence=0.86, bbox_xyxy=bbox,
        eligible_drivers=tuple(drivers),
    )


def _has_color(image, color_rgb):
    rgb = np.array(color_rgb, dtype=np.uint8)
    bgr = rgb[::-1]
    return bool(np.any(np.all(image == bgr, axis=2)))


def test_style_classification_deduplicates_drivers():
    assert get_box_style([]) == "no_order"
    assert get_box_style(["Driver A", "Driver A"]) == "single_driver"
    assert get_box_style(["Driver B", "Driver A"]) == "multiple_drivers"


def test_single_driver_uses_driver_color_and_dark_header():
    source = _image()
    annotated = draw_overlay(source, [_det(["Driver A"])])
    assert _has_color(annotated, DRIVER_STYLES["Driver A"].color_rgb)
    assert _has_color(annotated, HEADER_COLOR_RGB)
    assert not _has_color(annotated, SHARED_COLOR_RGB)
    assert np.array_equal(source, _image()), "Renderer must not modify its input"
    assert annotated.shape == source.shape


def test_multiple_drivers_use_gold_outline_and_individual_tags():
    annotated = draw_overlay(_image(), [_det(["Driver C", "Driver A", "Driver B"])])
    assert _has_color(annotated, SHARED_COLOR_RGB)
    for driver in ("Driver A", "Driver B", "Driver C"):
        assert _has_color(annotated, DRIVER_STYLES[driver].color_rgb)


def test_no_order_is_gray_without_driver_tags():
    annotated = draw_overlay(_image(), [_det([])])
    assert _has_color(annotated, NO_ORDER_COLOR_RGB)
    assert not _has_color(annotated, SHARED_COLOR_RGB)
    for style in DRIVER_STYLES.values():
        assert not _has_color(annotated, style.color_rgb)


def test_empty_detections_preserve_image():
    image = _image()
    result = draw_overlay(image, [])
    assert np.array_equal(result, image)
    assert result is not image


def test_boxes_at_image_edges_are_clipped_without_crash():
    img = _image()
    result = draw_overlay(img, [
        _det(["Driver A"], bbox=(-20, 0, 82, 74)),
        _det(["Driver A", "Driver B"], bbox=(350, 230, 500, 370)),
        _det([], bbox=(999, 999, 1010, 1010)),
    ])
    assert result.shape == img.shape
    assert not np.array_equal(result, img)


def test_long_labels_and_many_drivers_do_not_crash():
    drivers = [f"Driver {i}" for i in range(25)]
    result = draw_overlay(_image(), [_det(drivers, label="extremely_long_product_name_with_size_12_units")])
    assert result.shape == _image().shape
    assert _has_color(result, SHARED_COLOR_RGB)


def test_rejects_invalid_images_and_config():
    with pytest.raises(ValueError):
        draw_overlay(np.zeros((10, 10), dtype=np.uint8), [])
    with pytest.raises(ValueError):
        draw_overlay(_image(), [], max_driver_tags=-1)
