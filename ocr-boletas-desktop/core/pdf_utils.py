"""Utilidades para validar y renderizar PDFs."""

from __future__ import annotations

import logging
from pathlib import Path

import fitz
from PIL import Image

from config.settings import ALLOWED_EXTENSIONS, PDF_RENDER_DPI


logger = logging.getLogger(__name__)


class PDFError(Exception):
    """Error controlado relacionado con archivos PDF."""


def validate_pdf_path(file_path: str | Path) -> Path:
    """Valida que el archivo exista y tenga extension PDF."""

    path = Path(file_path)
    if not path.exists():
        raise PDFError("El archivo seleccionado no existe.")
    if not path.is_file():
        raise PDFError("La ruta seleccionada no corresponde a un archivo.")
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise PDFError("Seleccione un archivo PDF valido.")
    return path


def open_pdf(file_path: str | Path) -> fitz.Document:
    """Abre un PDF validado y devuelve el documento PyMuPDF."""

    path = validate_pdf_path(file_path)
    try:
        document = fitz.open(path)
    except Exception as exc:
        logger.exception("No se pudo abrir el PDF: %s", path)
        raise PDFError("No se pudo abrir el PDF. Puede estar corrupto o protegido.") from exc

    if document.page_count == 0:
        document.close()
        raise PDFError("El PDF no contiene paginas.")
    return document


def get_page_count(file_path: str | Path) -> int:
    """Devuelve el numero de paginas del PDF."""

    document = open_pdf(file_path)
    try:
        return document.page_count
    finally:
        document.close()


def render_page_to_image(
    file_path: str | Path,
    page_number: int = 0,
    dpi: int = PDF_RENDER_DPI,
) -> Image.Image:
    """Renderiza una pagina del PDF como imagen PIL RGB."""

    document = open_pdf(file_path)
    try:
        if page_number < 0 or page_number >= document.page_count:
            raise PDFError("La pagina solicitada no existe en el PDF.")

        page = document.load_page(page_number)
        scale = dpi / 72
        matrix = fitz.Matrix(scale, scale)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    except PDFError:
        raise
    except Exception as exc:
        logger.exception("Error al renderizar pagina %s de %s", page_number, file_path)
        raise PDFError("No se pudo renderizar la pagina del PDF.") from exc
    finally:
        document.close()


def render_first_page(file_path: str | Path, dpi: int = PDF_RENDER_DPI) -> Image.Image:
    """Renderiza la primera pagina del PDF."""

    return render_page_to_image(file_path=file_path, page_number=0, dpi=dpi)

