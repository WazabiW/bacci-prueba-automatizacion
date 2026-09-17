"""Carga y normalización de las fuentes.

Reglas aplicadas aquí (ver README, sección Decisiones):
  - Duplicados exactos de línea: se colapsan a uno.
  - Duplicados con uds_pedidas contradictorias: se toma el MAYOR y se marca
    la línea como `conflicto_uds`, conservando los valores en conflicto.
  - uds_enviadas > uds_pedidas: pendiente 0 y marca `sobreservido`.
  - Vacíos = desconocido, nunca 0.
  - Correos: upsert por message_id (reentregas no duplican).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import CRITERIO_CONFLICTO_UDS

CLAVE = ["pedido_id", "linea_id"]


def cargar_pedidos(ruta: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Devuelve (lineas_normalizadas, clientes, metricas_de_ingesta)."""
    pedidos = pd.read_excel(ruta, sheet_name="Pedidos")
    clientes = pd.read_excel(ruta, sheet_name="Clientes")

    m: dict = {"filas_origen": len(pedidos)}

    pedidos["pedido_id"] = pedidos["pedido_id"].astype(str).str.strip()
    pedidos["cliente_id"] = pedidos["cliente_id"].astype(str).str.strip()
    pedidos["linea_id"] = pedidos["linea_id"].astype("Int64")

    # 1) duplicados exactos
    antes = len(pedidos)
    pedidos = pedidos.drop_duplicates()
    m["duplicados_exactos"] = antes - len(pedidos)

    # 2) claves repetidas con contenido distinto
    dup = pedidos[pedidos.duplicated(CLAVE, keep=False)]
    m["claves_en_conflicto"] = dup.groupby(CLAVE).ngroups if len(dup) else 0

    conflictos = (
        dup.groupby(CLAVE)["uds_pedidas"]
        .agg(["min", "max"])
        .rename(columns={"min": "uds_pedidas_min", "max": "uds_pedidas_max"})
        .reset_index()
    )

    if CRITERIO_CONFLICTO_UDS == "max":
        idx = pedidos.groupby(CLAVE)["uds_pedidas"].idxmax()
    else:
        idx = pedidos.groupby(CLAVE)["uds_pedidas"].idxmin()
    lineas = pedidos.loc[idx].reset_index(drop=True)

    lineas = lineas.merge(conflictos, on=CLAVE, how="left")
    lineas["conflicto_uds"] = lineas["uds_pedidas_max"].notna()

    # 3) pendiente y anomalías de cantidad
    lineas["sobreservido"] = lineas["uds_enviadas"] > lineas["uds_pedidas"]
    lineas["uds_pendientes"] = (
        (lineas["uds_pedidas"] - lineas["uds_enviadas"]).clip(lower=0).astype(int)
    )

    # 4) integridad referencial contra el maestro
    clientes["cliente_id"] = clientes["cliente_id"].astype(str).str.strip()
    conocidos = set(clientes["cliente_id"])
    lineas["cliente_huerfano"] = ~lineas["cliente_id"].isin(conocidos)

    lineas["sin_fecha"] = lineas["fecha_compromiso"].isna()
    lineas["sin_precio"] = lineas["precio_unitario_eur"].isna()

    m["lineas_unicas"] = len(lineas)
    m["sobreservidas"] = int(lineas["sobreservido"].sum())
    m["sin_fecha"] = int(lineas["sin_fecha"].sum())
    m["sin_precio"] = int(lineas["sin_precio"].sum())
    m["cliente_huerfano"] = int(lineas["cliente_huerfano"].sum())
    m["con_pendiente"] = int((lineas["uds_pendientes"] > 0).sum())

    return lineas, clientes, m


def cargar_correos(rutas: list[Path],
                   corte: "pd.Timestamp | None" = None) -> tuple[pd.DataFrame, dict]:
    """Concatena lotes de correo, aplica el corte y deduplica por message_id.

    El corte es parte del enunciado (10/09 10:00, u 11:00 tras incorporar el
    lote): un correo posterior no se ha visto todavía y no puede influir en el
    resultado. Se aplica explícitamente para que el proceso sea reproducible
    aunque el buzón siga recibiendo mensajes.
    """
    trozos = [pd.read_excel(r, sheet_name="Correos") for r in rutas]
    correos = pd.concat(trozos, ignore_index=True)

    m = {"filas_origen": len(correos)}

    correos["message_id"] = correos["message_id"].astype(str).str.strip()
    correos["received_at"] = pd.to_datetime(correos["received_at"])
    for c in ("from", "to", "subject", "body"):
        correos[c] = correos[c].fillna("").astype(str)

    if corte is not None:
        antes = len(correos)
        correos = correos[correos["received_at"] <= corte]
        m["posteriores_al_corte"] = antes - len(correos)
    else:
        m["posteriores_al_corte"] = 0

    # upsert: un message_id es estable, una reentrega conserva el mismo id
    correos = (
        correos.sort_values("received_at")
        .drop_duplicates(subset=["message_id"], keep="last")
        .reset_index(drop=True)
    )

    m["reentregas_descartadas"] = m["filas_origen"] - len(correos)
    m["correos_unicos"] = len(correos)
    return correos, m
