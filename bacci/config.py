"""Parámetros de negocio.

Todo lo que es una DECISIÓN y no una restricción técnica vive aquí,
para que Bacci pueda cambiarlo sin tocar la lógica.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")

RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "datos"
RUTA_DB = RAIZ / "bacci.db"

# Cortes definidos en el enunciado
CORTE_INICIAL = datetime(2026, 9, 10, 10, 0, tzinfo=TZ)
CORTE_ACTUALIZACION = datetime(2026, 9, 10, 11, 0, tzinfo=TZ)

DATASETS = {
    "muestra": {
        "pedidos": "Pedidos_muestra.xlsx",
        "correos": ["Correos_muestra.xlsx"],
    },
    "full": {
        "pedidos": "Pedidos_full.xlsx",
        "correos": ["Correos_full.xlsx"],
    },
}
LOTE_ACTUALIZACION = "Correos_actualizacion.xlsx"


# --- Criterio de priorización -------------------------------------------------
# Escala 0-100. Tres KPIs que suman. Documentado en el README.

PESO_FECHA = {
    "vencida_mas_7d": 50,
    "vencida_1_7d": 40,
    "vence_hoy": 30,
    "vence_1_3d": 20,
    "vence_4_14d": 10,
    "vence_mas_14d": 0,
    "sin_fecha": 15,  # desconocido != sin urgencia
}

PESO_PETICION = {
    "cancelacion": 30,
    "adelanto": 25,
    "cambio_fecha": 20,
    "consulta_estado": 10,
    "sin_accion": 0,
    "sin_correo": 0,
}

# Percentil del volumen pendiente frente al resto de líneas con pendiente.
PESO_VOLUMEN = [(90, 20), (70, 15), (40, 10), (0, 5)]

# Criterio para duplicados con uds_pedidas contradictorias.
# "max" = se toma el mayor pendiente y se marca el conflicto para revisión.
CRITERIO_CONFLICTO_UDS = "max"
