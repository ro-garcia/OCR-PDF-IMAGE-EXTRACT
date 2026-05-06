"""Preprocesamiento de imagen con OpenCV para OCR."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class TableStructure:
    """Representa una tabla detectada por lineas horizontales y verticales."""

    bbox: tuple[int, int, int, int]
    row_lines: list[int]
    col_lines: list[int]

    @property
    def row_count(self) -> int:
        return max(0, len(self.row_lines) - 1)

    @property
    def col_count(self) -> int:
        return max(0, len(self.col_lines) - 1)


def pil_to_cv(image: Image.Image) -> np.ndarray:
    """Convierte PIL RGB a arreglo OpenCV BGR."""

    rgb = np.array(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def cv_to_pil(image: np.ndarray) -> Image.Image:
    """Convierte arreglo OpenCV a PIL."""

    if len(image.shape) == 2:
        return Image.fromarray(image)
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def to_grayscale(image: np.ndarray) -> np.ndarray:
    """Convierte la imagen a escala de grises."""

    if len(image.shape) == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def denoise(image: np.ndarray) -> np.ndarray:
    """Reduce ruido sin destruir detalles pequenos."""

    gray = to_grayscale(image)
    return cv2.fastNlMeansDenoising(gray, None, h=8, templateWindowSize=7, searchWindowSize=21)


def improve_contrast(image: np.ndarray) -> np.ndarray:
    """Mejora contraste local con CLAHE de forma moderada."""

    gray = to_grayscale(image)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def threshold_image(image: np.ndarray) -> np.ndarray:
    """Aplica threshold adaptativo suave para OCR."""

    gray = to_grayscale(image)
    return cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        9,
    )


def preprocess_for_ocr(image: Image.Image | np.ndarray) -> Image.Image:
    """Combina los pasos de preprocesamiento para OCR."""

    cv_image = pil_to_cv(image) if isinstance(image, Image.Image) else image
    gray = to_grayscale(cv_image)
    contrasted = improve_contrast(gray)
    cleaned = denoise(contrasted)
    thresholded = threshold_image(cleaned)
    return cv_to_pil(thresholded)


def preprocess_table_cell_for_ocr(image: Image.Image | np.ndarray) -> Image.Image:
    """Prepara una celda de tabla para OCR preservando texto pequeno."""

    cv_image = pil_to_cv(image) if isinstance(image, Image.Image) else image
    gray = to_grayscale(cv_image)
    contrasted = improve_contrast(gray)
    cleaned = cv2.GaussianBlur(contrasted, (3, 3), 0)
    _, thresholded = cv2.threshold(cleaned, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    height, width = thresholded.shape[:2]
    if width < 260 or height < 80:
        thresholded = cv2.resize(thresholded, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    return cv_to_pil(thresholded)


def _binary_for_lines(cv_image: np.ndarray) -> np.ndarray:
    gray = to_grayscale(cv_image)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        12,
    )


def _line_masks(binary: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    height, width = binary.shape[:2]
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(width // 28, 40), 1))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(height // 28, 35)))

    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel, iterations=1)
    return horizontal, vertical


def _collapse_positions(indices: np.ndarray, max_gap: int = 8) -> list[int]:
    if len(indices) == 0:
        return []

    groups: list[list[int]] = [[int(indices[0])]]
    for index in indices[1:]:
        value = int(index)
        if value - groups[-1][-1] <= max_gap:
            groups[-1].append(value)
        else:
            groups.append([value])

    return [int(round(sum(group) / len(group))) for group in groups]


def _line_positions(mask: np.ndarray, axis: int, min_ratio: float) -> list[int]:
    if axis == 0:
        projection = np.sum(mask > 0, axis=1)
        limit = mask.shape[1] * min_ratio
    else:
        projection = np.sum(mask > 0, axis=0)
        limit = mask.shape[0] * min_ratio

    indices = np.where(projection >= limit)[0]
    return _collapse_positions(indices)


def _add_edges(positions: list[int], maximum: int, tolerance: int = 18) -> list[int]:
    if not positions:
        return []

    result = sorted(set(positions))
    if result[0] > tolerance:
        result.insert(0, 0)
    if maximum - result[-1] > tolerance:
        result.append(maximum)
    return result


def _build_table_structure(cv_image: np.ndarray, bbox: tuple[int, int, int, int]) -> TableStructure | None:
    x, y, width, height = bbox
    if width <= 0 or height <= 0:
        return None

    crop = cv_image[y : y + height, x : x + width]
    binary = _binary_for_lines(crop)
    horizontal, vertical = _line_masks(binary)

    row_lines = _line_positions(horizontal, axis=0, min_ratio=0.28)
    col_lines = _line_positions(vertical, axis=1, min_ratio=0.18)
    row_lines = _add_edges(row_lines, height - 1)
    col_lines = _add_edges(col_lines, width - 1)

    if len(row_lines) < 5 or len(col_lines) < 6:
        return None

    return TableStructure(bbox=bbox, row_lines=row_lines, col_lines=col_lines)


def detect_plan_cargue_table(image: Image.Image | np.ndarray) -> TableStructure | None:
    """Detecta una tabla tipo PLAN DE CARGUE por su grilla visual."""

    cv_image = pil_to_cv(image) if isinstance(image, Image.Image) else image
    height, width = cv_image.shape[:2]
    binary = _binary_for_lines(cv_image)
    horizontal, vertical = _line_masks(binary)
    combined = cv2.add(horizontal, vertical)
    combined = cv2.dilate(combined, np.ones((3, 3), dtype=np.uint8), iterations=1)

    contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, candidate_width, candidate_height = cv2.boundingRect(contour)
        if candidate_width < width * 0.50 or candidate_height < height * 0.08:
            continue
        candidates.append((x, y, candidate_width, candidate_height))

    if not candidates:
        ys, xs = np.where(combined > 0)
        if len(xs) == 0 or len(ys) == 0:
            return None
        points = np.column_stack((xs, ys)).astype(np.int32)
        x, y, candidate_width, candidate_height = cv2.boundingRect(points)
        candidates.append((x, y, candidate_width, candidate_height))

    best_structure: TableStructure | None = None
    best_score = -1
    for x, y, candidate_width, candidate_height in candidates:
        pad = 6
        safe_x = max(0, x - pad)
        safe_y = max(0, y - pad)
        safe_right = min(width, x + candidate_width + pad)
        safe_bottom = min(height, y + candidate_height + pad)
        bbox = (safe_x, safe_y, safe_right - safe_x, safe_bottom - safe_y)

        structure = _build_table_structure(cv_image, bbox)
        if not structure:
            continue

        score = (structure.row_count * structure.col_count * 1000) + (bbox[2] * bbox[3])
        if score > best_score:
            best_score = score
            best_structure = structure

    return best_structure


def crop_table_cell(
    image: Image.Image,
    table: TableStructure,
    row: int,
    column: int,
    padding: int = 4,
) -> Image.Image:
    """Recorta una celda de una tabla detectada."""

    x, y, _width, _height = table.bbox
    left = x + table.col_lines[column] + padding
    right = x + table.col_lines[column + 1] - padding
    top = y + table.row_lines[row] + padding
    bottom = y + table.row_lines[row + 1] - padding

    left = max(x, left)
    top = max(y, top)
    right = max(left + 1, right)
    bottom = max(top + 1, bottom)
    return image.crop((left, top, right, bottom))
