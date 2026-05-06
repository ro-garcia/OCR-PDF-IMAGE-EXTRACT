"""Parser tolerante para extraer boletas Chevron desde texto OCR."""

from __future__ import annotations

import json
import re
from copy import deepcopy


HEADER_FIELDS = [
    "boleta_de_carga",
    "terminal_direccion",
    "contacto",
    "terminal",
    "conductor",
    "numero_tanque_siglas_unidad",
    "numero_cabezal_cabezal",
    "fecha",
    "transportador",
    "hora_inicio_cargue",
    "hora_final_cargue",
    "anotacion",
]

PRODUCT_TABLE_FIELDS = [
    "numero_entrega",
    "nombre_cliente",
    "nombre_producto",
    "cantidad",
]

COMPARTMENT_FIELDS = [
    "numero_compartimiento",
    "nombre_producto",
    "codigo_producto",
    "capacidad_de_cargue",
    "cantidad_a_cargar",
    "cantidad_cargada",
    "cantidad_total_en_transporte",
    "temperatura_de_cargue",
    "consumo_propio",
]

PRODUCT_KEYWORDS = (
    "GASOLINA",
    "DIESEL",
    "REGULAR",
    "PREMIUM",
    "PLUS",
    "BULK",
    "SUPER",
)

COMMON_OCR_REPLACEMENTS = (
    (r"Direcci[oó]n|Direcci.n|Direccién", "Direccion"),
    (r"N[eé]mere|N[ée]mero|Niimero|Niimera|Nimero|Namero", "Numero"),
    (r"BeAximero|Aximero", "Numero"),
    (r"Nembre", "Nombre"),
    (r"Kedigo|C[oó]digo", "Codigo"),
    (r"Caatidad", "Cantidad"),
    (r"cargadsa", "cargada"),
    (r"identificacin", "identificacion"),
    (r"wibutaria", "tributaria"),
    (r"cargue", "cargue"),
)


def build_empty_compartments() -> list[dict[str, str]]:
    """Devuelve siempre los 10 compartimientos vacios."""

    compartments: list[dict[str, str]] = []
    for number in range(1, 11):
        row = {field: "" for field in COMPARTMENT_FIELDS}
        row["numero_compartimiento"] = str(number)
        compartments.append(row)
    return compartments


def build_empty_result() -> dict:
    """Devuelve la estructura JSON vacia completa."""

    return {
        "encabezado": {field: "" for field in HEADER_FIELDS},
        "tabla_productos": [],
        "plan_de_cargue": {
            "compartimientos": build_empty_compartments(),
        },
    }


def empty_boleta_data(_archivo_origen: str = "") -> dict:
    """Alias de compatibilidad para la UI."""

    return build_empty_result()


def normalize_result(data: dict | None) -> dict:
    """Garantiza que existan todas las claves esperadas."""

    normalized = build_empty_result()
    if not isinstance(data, dict):
        return normalized

    header = data.get("encabezado", {})
    if isinstance(header, dict):
        for field in HEADER_FIELDS:
            normalized["encabezado"][field] = str(header.get(field, "") or "").strip()

    products = data.get("tabla_productos", [])
    if isinstance(products, list):
        for item in products:
            if not isinstance(item, dict):
                continue
            row = {field: str(item.get(field, "") or "").strip() for field in PRODUCT_TABLE_FIELDS}
            if any(row.values()):
                normalized["tabla_productos"].append(row)

    raw_compartments = data.get("plan_de_cargue", {}).get("compartimientos", [])
    by_number: dict[str, dict[str, str]] = {}
    if isinstance(raw_compartments, list):
        for item in raw_compartments:
            if not isinstance(item, dict):
                continue
            number = str(item.get("numero_compartimiento", "") or "").strip()
            if not number:
                continue
            row = {field: str(item.get(field, "") or "").strip() for field in COMPARTMENT_FIELDS}
            row["numero_compartimiento"] = number
            by_number[number] = row

    compartments = build_empty_compartments()
    for row in compartments:
        number = row["numero_compartimiento"]
        if number in by_number:
            row.update(by_number[number])
            row["numero_compartimiento"] = number
    normalized["plan_de_cargue"]["compartimientos"] = compartments
    return normalized


def clean_text(text: str) -> str:
    """Normaliza texto OCR preservando saltos utiles."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned_lines = []
    for line in normalized.splitlines():
        cleaned_line = clean_ocr_line(line)
        if cleaned_line:
            cleaned_lines.append(cleaned_line)
    normalized = "\n".join(cleaned_lines)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def clean_ocr_line(line: str) -> str:
    """Limpia ruido frecuente del OCR sin borrar datos operativos."""

    cleaned = line.strip()
    if not cleaned:
        return ""

    for pattern, replacement in COMMON_OCR_REPLACEMENTS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    if re.fullmatch(r"Chevron", cleaned, flags=re.IGNORECASE):
        return ""
    if re.search(r"\bCHEVRON\s+GUATEMALA\s+INC\.?", cleaned, flags=re.IGNORECASE):
        return "CHEVRON GUATEMALA INC."
    if re.search(r"\bGUATEMALA\s+GT\b", cleaned, flags=re.IGNORECASE):
        return "GUATEMALA GT"

    cleaned = re.sub(r"(?i)\bOur Family of Brands\b", "", cleaned)
    cleaned = re.sub(r"(?i)\b(craven|rence\s+RA\s+cas)\b", "", cleaned)
    cleaned = re.sub(r"[“”‘’´`]", "'", cleaned)
    cleaned = re.sub(r"[|_\[\]{}]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" :;-")


def _clean_value(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip(" :-#\t|")
    return value.strip(" :-#\t|")


def _format_contact(value: str) -> str:
    phones = re.findall(r"\b\d{4}-\d{4}\b", value)
    if phones:
        return " / ".join(phones)
    return _clean_value(value)


def _format_quantity(value: str) -> str:
    cleaned = (value or "").replace(",", ".")
    match = re.search(r"\b\d+(?:\.\d+)?\b", cleaned)
    if not match:
        return ""
    number = match.group(0)
    if "." not in number and len(number) > 3:
        number = f"{number[:-3]}.{number[-3:]}"
    return number


def normalize_product_name(value: str) -> str:
    """Normaliza nombres de producto a la forma esperada."""

    product = (value or "").upper()
    product = re.sub(r"[/|]+", " ", product)
    product = re.sub(r"\bIBULK\b|\bJBULK\b|\bBULKIBULK\b", "BULK", product)
    product = re.sub(r"\bS0O?0?\s*BULK\b", "S 500 BULK", product)
    product = re.sub(r"\b500\s+BULK\b", "S 500 BULK", product) if "DIESEL" in product else product
    product = re.sub(r"\bDIESEL\s+S\s+S\s+500\b", "DIESEL S 500", product)
    product = re.sub(r"\bBUL\s+K\b", "BULK", product)
    product = re.sub(r"\bBULK\s+BULK\b", "BULK", product)
    product = re.sub(r"[^A-Z0-9\s]", " ", product)
    product = re.sub(r"\s+", " ", product).strip()
    return product


def normalize_product_code(value: str) -> str:
    """Corrige codigos comunes leidos con ceros extra."""

    code = re.sub(r"\D+", "", value or "")
    if len(code) == 9 and code.startswith("3800"):
        return code[:3] + code[4:]
    if len(code) == 9 and code.startswith("8500"):
        return code[:-1]
    return code


def extract_field(patterns: list[str], text: str) -> str:
    """Devuelve el primer grupo encontrado para una lista de patrones."""

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return _clean_value(match.group(1))
    return ""


def _extract_header(text: str) -> dict[str, str]:
    header = {field: "" for field in HEADER_FIELDS}
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    header["boleta_de_carga"] = extract_field(
        [
            r"Boleta\s+de\s+Carga\s+del\s+Despacho\s+Numero\s*[:#-]?\s*([A-Z0-9-]+)",
            r"Despacho\s+Numero\s*[:#-]?\s*([A-Z0-9-]+)",
            r"Numero\s+de\s+Despacho\s*[:#-]?\s*([A-Z0-9-]+)",
        ],
        text,
    )
    header["fecha"] = extract_field(
        [
            r"\bFecha\s*[:#-]?\s*([0-9]{1,2}[-/][A-Z]{3}[-/][0-9]{2,4})",
            r"\bFecha\s*[:#-]?\s*([0-9]{1,2}[-/][0-9]{1,2}[-/][0-9]{2,4})",
        ],
        text,
    ).upper()

    header["transportador"] = extract_field(
        [r"Nombre\s+transportador\s*[:#= -]*([A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9 \t.,&'-]{3,})"],
        text,
    )

    for index, line in enumerate(lines):
        if not re.search(r"\bTerminal\s*/\s*Direccion\b", line, re.IGNORECASE):
            continue

        terminal_match = re.search(r"\bTerminal\b\s+([0-9]{2,})", line, re.IGNORECASE)
        if not terminal_match:
            terminal_match = re.search(r"Numero\s+de\s+contacto\s+([0-9]{2,})", line, re.IGNORECASE)
        if not terminal_match:
            terminal_match = re.search(r"([0-9]{2,})\.?\s*$", line)
        if terminal_match:
            header["terminal"] = terminal_match.group(1)
        elif index + 1 < len(lines):
            terminal_next = re.search(r"\bTerminal\b\s+([0-9]{2,})", lines[index + 1], re.IGNORECASE)
            if terminal_next:
                header["terminal"] = terminal_next.group(1)

        terminal_line = lines[index + 1] if index + 1 < len(lines) else ""
        direction_line = lines[index + 2] if index + 2 < len(lines) else ""
        cabezal_line = lines[index + 3] if index + 3 < len(lines) else ""

        terminal_name = re.split(r"\bTel\b|Nombre\s+conductor|Numero\s+tanque", terminal_line, flags=re.IGNORECASE)[0]
        direction_name = re.split(r"Numero\s+tanque|tanque\s*/?\s*siglas", direction_line, flags=re.IGNORECASE)[0]
        header["terminal_direccion"] = _clean_value(f"{terminal_name} {direction_name}")

        header["contacto"] = _format_contact(terminal_line)

        conductor_match = re.search(
            r"Nombre\s+conductor\s*([0-9]+\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s.'-]{3,})$",
            terminal_line,
            re.IGNORECASE,
        )
        if conductor_match:
            header["conductor"] = _clean_value(conductor_match.group(1))

        tank_match = re.search(
            r"(?:Numero\s+tanque\s*/?\s*siglas\s+unidad|Numero\s+tanque|tanque)\s*([A-Z0-9-]{3,})",
            direction_line,
            re.IGNORECASE,
        )
        if tank_match:
            header["numero_tanque_siglas_unidad"] = _clean_value(tank_match.group(1))

        cabezal_match = re.search(r"Numero\s+cabezote\s*/?\s*cabezal\s*([A-Z0-9-]+)", cabezal_line, re.IGNORECASE)
        if not cabezal_match:
            cabezal_match = re.search(r"Numero\s+cabezal\s*/?\s*cabezal\s*([A-Z0-9-]+)", cabezal_line, re.IGNORECASE)
        if cabezal_match:
            header["numero_cabezal_cabezal"] = _clean_value(cabezal_match.group(1))
        break

    annotation_match = re.search(r"\b([0-9]{5,}\s+AL\W*\s*[0-9]{5,}\s+TOTAL\s+[0-9]+)\b", text, re.IGNORECASE)
    if annotation_match:
        header["anotacion"] = re.sub(r"\s+", " ", annotation_match.group(1).replace("AL)", "AL")).strip().upper()

    start_match = re.search(r"Hora\s+inicio\s+cargue\s*[:#-]?\s*([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)", text, re.IGNORECASE)
    final_match = re.search(r"Hora\s+final\s+cargue\s*[:#-]?\s*([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)", text, re.IGNORECASE)
    if start_match:
        header["hora_inicio_cargue"] = start_match.group(1)
    if final_match:
        header["hora_final_cargue"] = final_match.group(1)

    return header


def _looks_like_product(text: str) -> bool:
    upper = text.upper()
    return any(keyword in upper for keyword in PRODUCT_KEYWORDS)


def extract_tabla_productos(text: str) -> list[dict[str, str]]:
    """Extrae la tabla resumen de productos desde texto OCR lineal."""

    products: list[dict[str, str]] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    active = False

    for line in lines:
        if re.search(r"Numero\s+de\s+Entrega.*Nombre\s+Cliente.*Nombre\s+Producto.*Cantidad", line, re.IGNORECASE):
            active = True
            continue
        if active and re.search(r"PLAN\s+DE\s+CARGUE", line, re.IGNORECASE):
            break
        if not active or not _looks_like_product(line):
            continue

        quantity_matches = re.findall(r"\b\d{1,5}[,.]\d{3}\b", line)
        quantity = _format_quantity(quantity_matches[-1]) if quantity_matches else ""
        clean_line = re.sub(r"\b\d{1,5}[,.]\d{3}\b.*$", "", line).strip()

        delivery = ""
        customer = ""
        product_text = clean_line
        row_match = re.match(
            r"([0-9]{6,})\s+(.+?)\s+(?=GASOLINA|DIESEL|REGULAR|PREMIUM|PLUS|BULK)",
            clean_line,
            re.IGNORECASE,
        )
        if row_match:
            delivery = row_match.group(1)
            customer = _clean_value(row_match.group(2))
            product_text = clean_line[row_match.end(2) :].strip()

        product_name = normalize_product_name(product_text)
        if product_name or quantity:
            products.append(
                {
                    "numero_entrega": delivery,
                    "nombre_cliente": customer,
                    "nombre_producto": product_name,
                    "cantidad": quantity,
                }
            )

    return products


def build_product_table_from_compartments(
    compartments: list[dict[str, str]],
    numero_entrega: str = "",
    nombre_cliente: str = "",
) -> list[dict[str, str]]:
    """Agrupa compartimientos por producto para completar tabla_productos."""

    grouped: dict[str, float] = {}
    order: list[str] = []
    for compartment in compartments:
        product = normalize_product_name(str(compartment.get("nombre_producto", "")))
        quantity = str(compartment.get("cantidad_a_cargar", "") or "").strip()
        if not product or not quantity:
            continue
        try:
            value = float(quantity.replace(",", ""))
        except ValueError:
            continue
        if product not in grouped:
            grouped[product] = 0.0
            order.append(product)
        grouped[product] += value

    rows: list[dict[str, str]] = []
    for index, product in enumerate(order):
        rows.append(
            {
                "numero_entrega": numero_entrega if index == 0 else "",
                "nombre_cliente": nombre_cliente if index == 0 else "",
                "nombre_producto": product,
                "cantidad": f"{grouped[product]:.3f}",
            }
        )
    return rows


def parse_boleta(text: str, archivo_origen: str = "") -> dict:
    """Parsea texto OCR y devuelve la estructura final esperada."""

    _ = archivo_origen
    cleaned = clean_text(text or "")
    data = build_empty_result()
    data["encabezado"].update(_extract_header(cleaned))
    data["tabla_productos"] = extract_tabla_productos(cleaned)
    return normalize_result(data)


def debug_parse(text: str) -> None:
    """Imprime el resultado del parser para pruebas manuales."""

    print(json.dumps(parse_boleta(text), ensure_ascii=False, indent=2))
