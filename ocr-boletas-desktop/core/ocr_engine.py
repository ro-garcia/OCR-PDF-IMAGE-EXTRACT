"""Motor OCR basado en pytesseract."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pytesseract
from pytesseract import Output
from PIL import Image

from config.settings import COMMON_TESSERACT_PATHS, OCR_CONFIG, OCR_LANGUAGE, TESSERACT_CMD


logger = logging.getLogger(__name__)
_TESSERACT_READY = False


class OCRError(Exception):
    """Error controlado del motor OCR."""


def configure_tesseract() -> None:
    """Configura la ruta de Tesseract si esta definida o se detecta en Windows."""

    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
        return

    if shutil.which("tesseract"):
        return

    for candidate in COMMON_TESSERACT_PATHS:
        if Path(candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return


def is_tesseract_available() -> bool:
    """Verifica si Tesseract esta disponible."""

    global _TESSERACT_READY
    if _TESSERACT_READY:
        return True

    configure_tesseract()
    try:
        _ = pytesseract.get_tesseract_version()
        _TESSERACT_READY = True
        return True
    except Exception:
        return False


def run_ocr(image: Image.Image, language: str = OCR_LANGUAGE, config: str = OCR_CONFIG) -> str:
    """Ejecuta OCR sobre una imagen preprocesada."""

    configure_tesseract()
    if not is_tesseract_available():
        raise OCRError(
            "Tesseract OCR no esta instalado o no se encontro. Instale Tesseract "
            "o configure la ruta en config/settings.py."
        )

    try:
        text = pytesseract.image_to_string(image, lang=language, config=config)
    except pytesseract.TesseractNotFoundError as exc:
        logger.exception("Tesseract no encontrado")
        raise OCRError(
            "Tesseract OCR no esta instalado o no esta en PATH. Revise la configuracion."
        ) from exc
    except pytesseract.TesseractError as exc:
        logger.exception("Tesseract devolvio error")
        raise OCRError("Tesseract no pudo procesar la imagen seleccionada.") from exc
    except Exception as exc:
        logger.exception("Error inesperado al ejecutar OCR")
        raise OCRError("Ocurrio un error al ejecutar el OCR.") from exc

    return text.strip()


def run_ocr_cell(image: Image.Image, language: str = OCR_LANGUAGE, config: str = "--psm 6") -> str:
    """Ejecuta OCR sobre una celda de tabla."""

    return run_ocr(image=image, language=language, config=config)


def get_ocr_boxes(
    image: Image.Image,
    language: str = OCR_LANGUAGE,
    config: str = OCR_CONFIG,
    min_confidence: int = 45,
) -> list[dict[str, int | str]]:
    """Devuelve cajas de texto OCR para dibujarlas sobre la vista PDF."""

    configure_tesseract()
    if not is_tesseract_available():
        raise OCRError(
            "Tesseract OCR no esta instalado o no se encontro. Instale Tesseract "
            "o configure la ruta en config/settings.py."
        )

    try:
        data = pytesseract.image_to_data(image, lang=language, config=config, output_type=Output.DICT)
    except Exception as exc:
        logger.exception("No se pudieron obtener cajas OCR")
        raise OCRError("No se pudieron obtener las posiciones del texto OCR.") from exc

    boxes: list[dict[str, int | str]] = []
    for index, text in enumerate(data.get("text", [])):
        value = str(text or "").strip()
        if not value:
            continue
        try:
            confidence = float(data["conf"][index])
        except (ValueError, TypeError):
            confidence = -1
        if confidence < min_confidence:
            continue

        boxes.append(
            {
                "x": int(data["left"][index]),
                "y": int(data["top"][index]),
                "w": int(data["width"][index]),
                "h": int(data["height"][index]),
                "text": value,
            }
        )
    return boxes
