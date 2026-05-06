"""Configuracion global de OCR Boletas Desktop."""

from __future__ import annotations

import logging
import os
from pathlib import Path


APP_NAME = "OCR Boletas"
APP_VERSION = "1.0.0"

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"
SAMPLES_DIR = BASE_DIR / "samples"

ALLOWED_EXTENSIONS = {".pdf"}
PDF_RENDER_DPI = 200
OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "eng")
OCR_CONFIG = os.getenv("OCR_CONFIG", "--psm 6")

# Si Tesseract no esta en PATH, definir esta variable de entorno o editarla aqui.
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")

COMMON_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

CRITICAL_FIELDS = ["numero_despacho", "fecha", "cliente", "productos"]


def ensure_directories() -> None:
    """Crea las carpetas operativas si no existen."""

    for directory in (OUTPUT_DIR, LOGS_DIR, SAMPLES_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def setup_logging() -> None:
    """Configura logging basico a archivo."""

    ensure_directories()
    log_file = LOGS_DIR / "ocr_boletas.log"
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        encoding="utf-8",
    )

