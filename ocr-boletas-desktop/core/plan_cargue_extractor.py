"""Extraccion tabular del PLAN DE CARGUE."""

from __future__ import annotations

import logging
import re
import unicodedata

from PIL import Image

from core.image_processing import (
    crop_table_cell,
    detect_plan_cargue_table,
    preprocess_table_cell_for_ocr,
)
from core.ocr_engine import run_ocr_cell
from core.parser import build_empty_compartments, normalize_product_code, normalize_product_name


logger = logging.getLogger(__name__)

PLAN_PRODUCT_KEYWORDS = (
    "GASOLINA",
    "DIESEL",
    "REGULAR",
    "PREMIUM",
    "PLUS",
    "BULK",
    "SUPER",
)


def normalize_text(value: str) -> str:
    """Normaliza texto para comparar etiquetas OCR."""

    without_accents = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Z0-9./\s-]+", " ", without_accents.upper())
    return re.sub(r"\s+", " ", cleaned).strip()


def clean_cell_text(value: str) -> str:
    """Limpia texto OCR de una celda."""

    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", line).strip(" :|") for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _ocr_table_cell(
    page_image: Image.Image,
    table,
    row: int,
    column: int,
    config: str = "--psm 6",
    padding: int = 4,
    use_preprocessing: bool = True,
) -> str:
    cell_image = crop_table_cell(page_image, table, row, column, padding=padding)
    processed = preprocess_table_cell_for_ocr(cell_image) if use_preprocessing else cell_image
    return clean_cell_text(run_ocr_cell(processed, config=config))


def _find_row(label_texts: dict[int, str], required_terms: tuple[str, ...], optional_terms: tuple[str, ...] = ()) -> int | None:
    for row, label in label_texts.items():
        normalized = normalize_text(label)
        if all(term in normalized for term in required_terms):
            if not optional_terms or any(term in normalized for term in optional_terms):
                return row
    return None


def _extract_compartment(value: str, fallback: int) -> str:
    normalized = normalize_text(value)
    match = re.search(r"\b([0-9]{1,2})\b", normalized)
    if match:
        number = int(match.group(1))
        if 1 <= number <= 10:
            return str(number)
        if str(number).startswith(str(fallback)) and 1 <= fallback <= 10:
            return str(fallback)
    return str(fallback)


def _extract_quantity(value: str) -> str:
    normalized = value.replace(",", "")
    matches = re.findall(r"\b\d+(?:\.\d+)?\b", normalized)
    if not matches:
        return ""
    return matches[-1]


def _looks_like_product(value: str) -> bool:
    normalized = normalize_text(value)
    has_keyword = any(keyword in normalized for keyword in PLAN_PRODUCT_KEYWORDS)
    has_product_code = re.search(r"\b\d{6,}\b", normalized) is not None
    return has_keyword or has_product_code


def _parse_product_cell(value: str) -> tuple[str, str]:
    normalized_lines = [normalize_text(line) for line in clean_cell_text(value).splitlines()]
    joined = " ".join(line for line in normalized_lines if line)
    joined = re.sub(r"\b(NOMBRE PRODUCTO|CODIGO DE PRODUCTO|CODIGO PRODUCTO|PRODUCTO|CODIGO)\b", " ", joined)
    joined = re.sub(r"\s+", " ", joined).strip()

    code_matches = list(re.finditer(r"\b\d{6,}\b", joined))
    product_code = code_matches[-1].group(0) if code_matches else ""
    product_name = joined
    if product_code:
        product_name = (joined[: code_matches[-1].start()] + " " + joined[code_matches[-1].end() :]).strip()

    product_name = normalize_product_name(product_name)
    return product_name, normalize_product_code(product_code)


def extract_plan_cargue_products(page_image: Image.Image) -> list[dict[str, str]]:
    """Extrae productos por compartimiento desde la tabla PLAN DE CARGUE."""

    compartments = extract_plan_cargue_compartments(page_image)
    products: list[dict[str, str]] = []
    for compartment in compartments:
        if compartment.get("nombre_producto") or compartment.get("cantidad_a_cargar"):
            products.append(
                {
                    "compartimiento": compartment["numero_compartimiento"],
                    "producto": compartment["nombre_producto"],
                    "codigo_producto": compartment["codigo_producto"],
                    "cantidad": compartment["cantidad_a_cargar"],
                }
            )
    return products


def extract_plan_cargue_compartments(page_image: Image.Image) -> list[dict[str, str]]:
    """Extrae el PLAN DE CARGUE y devuelve siempre 10 compartimientos."""

    table = detect_plan_cargue_table(page_image)
    if not table:
        return build_empty_compartments()

    cell_cache: dict[tuple[int, int, str, int, str], str] = {}

    def read_cell(
        row: int,
        column: int,
        config: str = "--psm 6",
        padding: int = 4,
        use_preprocessing: bool = True,
    ) -> str:
        key = (row, column, config, padding, str(use_preprocessing))
        if key not in cell_cache:
            cell_cache[key] = _ocr_table_cell(
                page_image,
                table,
                row,
                column,
                config=config,
                padding=padding,
                use_preprocessing=use_preprocessing,
            )
        return cell_cache[key]

    label_texts: dict[int, str] = {}
    for row in range(table.row_count):
        try:
            label_texts[row] = read_cell(row, 0)
        except Exception:
            logger.debug("No se pudo leer etiqueta de fila %s", row, exc_info=True)
            label_texts[row] = ""

    product_row = _find_row(label_texts, ("PRODUCTO",), ("NOMBRE", "CODIGO"))
    quantity_row = _find_row(label_texts, ("CANTIDAD", "CARGAR"))
    compartment_row = _find_row(label_texts, ("COMPART",))
    capacity_row = _find_row(label_texts, ("CAPACIDAD", "CARGUE"))
    loaded_row = _find_row(label_texts, ("CANTIDAD", "CARGADA"))
    total_row = _find_row(label_texts, ("TOTAL", "TRANSPORTE"))
    temperature_row = _find_row(label_texts, ("TEMPERATURA", "CARGUE"))
    own_use_row = _find_row(label_texts, ("CONSUM",))

    if product_row is None:
        product_row = _guess_product_row(page_image, table, read_cell)
    if quantity_row is None and product_row is not None:
        quantity_row = product_row + 2 if product_row + 2 < table.row_count else None
    if compartment_row is None and product_row is not None:
        compartment_row = max(0, product_row - 1)

    if product_row is None:
        return build_empty_compartments()

    by_number = {row["numero_compartimiento"]: row for row in build_empty_compartments()}
    data_columns = range(1, table.col_count)
    for column in data_columns:
        try:
            product_text = read_cell(product_row, column)
        except Exception:
            logger.debug("No se pudo leer producto en columna %s", column, exc_info=True)
            product_text = ""

        quantity_text = ""
        if quantity_row is not None:
            try:
                quantity_text = read_cell(
                    quantity_row,
                    column,
                    config="--psm 7 -c tessedit_char_whitelist=0123456789.,$[]",
                    padding=0,
                    use_preprocessing=False,
                )
            except Exception:
                logger.debug("No se pudo leer cantidad en columna %s", column, exc_info=True)

        if not _looks_like_product(product_text):
            continue

        compartment_text = ""
        if compartment_row is not None:
            try:
                compartment_text = read_cell(
                    compartment_row,
                    column,
                    config="--psm 7 -c tessedit_char_whitelist=0123456789",
                    padding=0,
                    use_preprocessing=False,
                )
            except Exception:
                logger.debug("No se pudo leer compartimiento en columna %s", column, exc_info=True)

        product_name, product_code = _parse_product_cell(product_text)
        quantity = _extract_quantity(quantity_text)

        if not product_name and not quantity:
            continue

        number = _extract_compartment(compartment_text, fallback=column)
        if number not in by_number:
            continue

        by_number[number]["nombre_producto"] = product_name
        by_number[number]["codigo_producto"] = product_code
        by_number[number]["cantidad_a_cargar"] = quantity
        by_number[number]["capacidad_de_cargue"] = _read_optional_quantity(read_cell, capacity_row, column)
        by_number[number]["cantidad_cargada"] = _read_optional_quantity(read_cell, loaded_row, column)
        by_number[number]["cantidad_total_en_transporte"] = _read_optional_quantity(read_cell, total_row, column)
        by_number[number]["temperatura_de_cargue"] = _read_optional_quantity(read_cell, temperature_row, column)
        by_number[number]["consumo_propio"] = _read_optional_quantity(read_cell, own_use_row, column)

    return [by_number[str(number)] for number in range(1, 11)]


def _read_optional_quantity(read_cell, row: int | None, column: int) -> str:
    if row is None:
        return ""
    try:
        text = read_cell(
            row,
            column,
            config="--psm 7 -c tessedit_char_whitelist=0123456789.,",
            padding=0,
            use_preprocessing=False,
        )
    except Exception:
        return ""
    if not re.search(r"\d+[,.]\d+", text):
        return ""
    return _extract_quantity(text)


def _guess_product_row(page_image: Image.Image, table, read_cell) -> int | None:
    """Busca la fila de productos cuando la etiqueta izquierda no se leyo bien."""

    best_row: int | None = None
    best_score = 0
    sample_columns = range(1, min(table.col_count, 6))
    for row in range(table.row_count):
        score = 0
        for column in sample_columns:
            try:
                if _looks_like_product(read_cell(row, column)):
                    score += 1
            except Exception:
                continue
        if score > best_score:
            best_score = score
            best_row = row

    return best_row if best_score > 0 else None
