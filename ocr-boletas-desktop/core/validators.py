"""Validaciones amigables para la estructura JSON final."""

from __future__ import annotations


def validate_required_fields(data: dict) -> list[str]:
    """Valida campos importantes y devuelve advertencias amigables."""

    warnings: list[str] = []
    header = data.get("encabezado", {})
    labels = {
        "boleta_de_carga": "Boleta de carga",
        "fecha": "Fecha",
        "terminal_direccion": "Terminal/Direccion",
    }

    for field, label in labels.items():
        if not str(header.get(field, "") or "").strip():
            warnings.append(f"El campo {label} esta vacio.")

    if not data.get("tabla_productos"):
        warnings.append("La tabla de productos no tiene filas.")

    return warnings


def validate_product_quantities(data: dict) -> list[str]:
    """Advierte si las cantidades no parecen numericas."""

    warnings: list[str] = []
    for index, product in enumerate(data.get("tabla_productos", []), start=1):
        quantity = str(product.get("cantidad", "")).strip()
        if quantity and not _is_number(quantity):
            warnings.append(f"La cantidad de tabla_productos fila {index} no parece numerica.")

    compartments = data.get("plan_de_cargue", {}).get("compartimientos", [])
    for index, compartment in enumerate(compartments, start=1):
        quantity = str(compartment.get("cantidad_a_cargar", "")).strip()
        if quantity and not _is_number(quantity):
            warnings.append(f"La cantidad a cargar del compartimiento {index} no parece numerica.")

    return warnings


def validate_before_export(data: dict) -> list[str]:
    """Valida datos antes de exportar. No bloquea por si sola."""

    return validate_required_fields(data) + validate_product_quantities(data)


def _is_number(value: str) -> bool:
    try:
        float(value.replace(",", ""))
        return True
    except ValueError:
        return False
