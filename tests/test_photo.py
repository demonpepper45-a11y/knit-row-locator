from __future__ import annotations

import cv2
import numpy as np
import pytest

from core.imageio import decode_image_bytes
from core.photo import read_photo
from core.synth import DEFAULT_PALETTE, make_unique_chart, render_photo
from core.types import ChartGrid, GridInputError


@pytest.fixture(scope="module")
def photo_case():
    cells = make_unique_chart(rows=10, cols=6, window_start=2, window_height=4, seed=4242)
    chart = ChartGrid(cells=cells, palette=DEFAULT_PALETTE)
    photo = render_photo(chart, 2, 4, seed=301, cell=40, margin=40, top_extra=100)
    return chart, photo


def _canonical(cells: np.ndarray, reference: np.ndarray) -> np.ndarray:
    if np.array_equal(cells, reference):
        return cells
    if np.array_equal(cells, 1 - reference):
        return 1 - cells
    raise AssertionError("观测矩阵既不相同也不互补")


def test_clean_photo_observation_matches_truth(photo_case) -> None:
    chart, photo = photo_case
    result = read_photo(photo.image, photo.corners, chart.stitches, 4)
    window = chart.cells[2:6]
    observed = result.observed

    assert observed.shape == (4, 6)
    assert np.array_equal(_canonical(observed.cells, window), window)
    assert observed.coverage == pytest.approx(1.0)
    assert observed.weights.min() > 0.4
    assert observed.weights.mean() > 0.6
    assert result.quality["mean_purity"] > 0.9
    assert result.quality["color_separation"] > 30
    assert result.overlay.shape[0] == result.warp_size[1] + 56 + 46
    assert result.overlay.shape[1] == result.warp_size[0]
    assert result.source_preview.shape == photo.image.shape


def test_top_row_is_latest_completed_row(photo_case) -> None:
    chart, photo = photo_case
    result = read_photo(photo.image, photo.corners, chart.stitches, 4)
    window = chart.cells[2:6]
    swap = not np.array_equal(result.observed.cells, window)
    expected = (1 - window) if swap else window
    # 内部第 0 行 = 观测区底部 = 图解较早一行；内部最后一行 = 照片顶部 = 最新完成行
    assert np.array_equal(result.observed.cells[0], expected[0])
    assert np.array_equal(result.observed.cells[-1], expected[-1])
    assert not np.array_equal(expected[0], expected[-1])


def test_homography_maps_four_corners(photo_case) -> None:
    chart, photo = photo_case
    result = read_photo(photo.image, photo.corners, chart.stitches, 4)
    width, height = result.warp_size
    mapped = cv2.perspectiveTransform(
        np.asarray(photo.corners, dtype=np.float32).reshape(-1, 1, 2),
        result.homography,
    ).reshape(-1, 2)
    expected = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32
    )
    assert np.allclose(mapped, expected, atol=0.05)


def test_blur_and_low_contrast_are_flagged(photo_case) -> None:
    chart, _ = photo_case
    blurred = render_photo(chart, 2, 4, seed=302, cell=40, blur_sigma=2.5)
    blur_result = read_photo(blurred.image, blurred.corners, chart.stitches, 4)
    assert blur_result.quality["blur_score"] < 30
    assert any("模糊" in note for note in blur_result.notes)
    assert blur_result.quality["mean_weight"] < 0.8

    low = render_photo(chart, 2, 4, seed=303, cell=40, contrast_scale=0.12)
    low_result = read_photo(low.image, low.corners, chart.stitches, 4)
    assert low_result.quality["color_separation"] < 25
    assert low_result.quality["coverage"] < 0.75 or low_result.quality["mean_weight"] < 0.3
    joined = " ".join(low_result.notes)
    assert ("对比" in joined) or ("区分" in joined) or ("无证据" in joined)


def test_jpeg_roundtrip(photo_case) -> None:
    chart, photo = photo_case
    ok, buffer = cv2.imencode(".jpg", photo.image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    assert ok
    decoded = decode_image_bytes(buffer.tobytes(), source="测试 JPEG")
    result = read_photo(decoded, photo.corners, chart.stitches, 4)
    window = chart.cells[2:6]
    canonical = result.observed.cells
    if not np.array_equal(canonical, window) and np.array_equal(canonical, 1 - window):
        canonical = 1 - canonical
    agreement = float(np.mean(canonical == window))
    assert agreement >= 0.95
    assert result.observed.coverage == pytest.approx(1.0)


def test_reversed_corner_order_rejected(photo_case) -> None:
    chart, photo = photo_case
    with pytest.raises(GridInputError, match="顺序反了"):
        read_photo(photo.image, photo.corners[::-1], chart.stitches, 4)


def test_bowtie_corners_rejected(photo_case) -> None:
    _, photo = photo_case
    bowtie = np.array([[50, 50], [250, 50], [50, 250], [250, 250]], dtype=np.float64)
    with pytest.raises(GridInputError, match="凸四边形"):
        read_photo(photo.image, bowtie, 6, 4)


def test_out_of_bounds_corner_rejected(photo_case) -> None:
    chart, photo = photo_case
    corners = np.array(photo.corners, dtype=np.float64)
    corners[0, 0] = -10
    with pytest.raises(GridInputError, match="超出照片范围"):
        read_photo(photo.image, corners, chart.stitches, 4)


def test_low_resolution_rejected() -> None:
    image = np.full((100, 100, 3), 180, dtype=np.uint8)
    corners = [[10, 10], [34, 10], [34, 50], [10, 50]]
    with pytest.raises(GridInputError, match="分辨率过低"):
        read_photo(image, corners, 12, 4)


def test_invalid_counts_rejected(photo_case) -> None:
    chart, photo = photo_case
    with pytest.raises(GridInputError, match="至少为 1"):
        read_photo(photo.image, photo.corners, chart.stitches, 0)
    with pytest.raises(GridInputError, match="必须是整数"):
        read_photo(photo.image, photo.corners, 3.5, 4)
