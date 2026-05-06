"""Exportacion de datos de boletas a JSON."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from config.settings import OUTPUT_DIR
from core.parser import normalize_result


def data_to_json(data: dict) -> str:
    """Convierte datos a JSON UTF-8 indentado."""

    return json.dumps(normalize_result(data), ensure_ascii=False, indent=2)


def suggest_filename(data: dict) -> str:
    """Genera un nombre sugerido para el JSON."""

    normalized = normalize_result(data)
    numero = str(normalized.get("encabezado", {}).get("boleta_de_carga", "")).strip()
    if numero:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", numero).strip("_")
        return f"boleta_{safe}.json"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"boleta_{timestamp}.json"


def save_json(data: dict, file_path: str | Path | None = None) -> Path:
    """Guarda JSON en archivo y devuelve la ruta final."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = Path(file_path) if file_path else OUTPUT_DIR / suggest_filename(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data_to_json(data), encoding="utf-8")
    return path
