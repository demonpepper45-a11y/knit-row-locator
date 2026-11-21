"""颜色工具：Lab 转换、确定性的二均值聚类、调色板提取。

聚类刻意不使用随机初始化（不使用 ``cv2.kmeans``），以保证同样的输入
永远得到同样的标签，便于测试和演示复现。
"""

from __future__ import annotations

import numpy as np

import cv2


def bgr_to_lab(colors: np.ndarray) -> np.ndarray:
    """把 ``(N, 3)`` 的 BGR 颜色（0–255）转换为 ``(N, 3)`` 的 Lab float32。"""
    arr = np.asarray(colors)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise ValueError(f"颜色数组应为 (N, 3)，实际为 {arr.shape}。")
    u8 = np.clip(arr, 0, 255).astype(np.uint8).reshape(-1, 1, 3)
    lab = cv2.cvtColor(u8, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    return lab


def lab_to_bgr(lab: np.ndarray) -> np.ndarray:
    arr = np.asarray(lab, dtype=np.float32).reshape(-1, 1, 3)
    return cv2.cvtColor(arr, cv2.COLOR_LAB2BGR).reshape(-1, 3)


def _sq_dists(points: np.ndarray, centers: np.ndarray) -> np.ndarray:
    diff = points[:, None, :] - centers[None, :, :]
    return np.einsum("ijk,ijk->ij", diff, diff)


def two_means(points: np.ndarray, max_iter: int = 80) -> tuple[np.ndarray, np.ndarray]:
    """确定性二均值聚类。

    初始化取距离最远的一对样本。返回 ``(centers, labels)``，centers 形状
    ``(2, d)``。当所有样本完全相同时两个中心重合，距离为 0。
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 1:
        raise ValueError("聚类至少需要一个二维样本。")
    if pts.shape[0] == 1:
        return np.vstack([pts[0], pts[0]]), np.zeros(1, dtype=np.int64)

    dist = _sq_dists(pts, pts)
    i, j = np.unravel_index(int(np.argmax(dist)), dist.shape)
    centers = np.vstack([pts[i], pts[j]]).astype(np.float64)
    labels = np.zeros(pts.shape[0], dtype=np.int64)
    if dist[i, j] <= 1e-12:
        return centers, labels

    for _ in range(max_iter):
        labels = _sq_dists(pts, centers).argmin(axis=1)
        new_centers = centers.copy()
        for k in (0, 1):
            members = pts[labels == k]
            if members.size:
                new_centers[k] = members.mean(axis=0)
            else:  # 空簇：放回原中心，避免塌缩
                new_centers[k] = centers[k]
        if np.allclose(new_centers, centers, atol=1e-6):
            centers = new_centers
            break
        centers = new_centers

    labels = _sq_dists(pts, centers).argmin(axis=1)
    # 保证标签 0 是较暗的一簇（Lab 的 L 通道更小），便于稳定复现
    if centers[0, 0] > centers[1, 0]:
        centers = centers[[1, 0]]
        labels = 1 - labels
    return centers, labels


def nearest_centers(points: np.ndarray, centers: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """返回每个样本最近的簇标签与距离。"""
    d2 = _sq_dists(np.asarray(points, dtype=np.float64), np.asarray(centers, dtype=np.float64))
    labels = d2.argmin(axis=1)
    distances = np.sqrt(d2[np.arange(len(labels)), labels])
    return labels.astype(np.int64), distances


def cluster_palette(colors: np.ndarray, labels: np.ndarray) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """按簇求平均 BGR 颜色，作为展示用调色板。"""
    arr = np.asarray(colors, dtype=np.float64)
    labels = np.asarray(labels)
    palette: list[tuple[int, int, int]] = []
    for k in (0, 1):
        members = arr[labels == k]
        if members.size == 0:
            palette.append((128, 128, 128))
        else:
            mean = np.clip(np.rint(members.mean(axis=0)), 0, 255).astype(int)
            palette.append((int(mean[0]), int(mean[1]), int(mean[2])))
    return palette[0], palette[1]


def separation(centers: np.ndarray) -> float:
    """两个 Lab 中心的欧氏色差。"""
    return float(np.linalg.norm(np.asarray(centers[0], dtype=np.float64) - np.asarray(centers[1], dtype=np.float64)))
