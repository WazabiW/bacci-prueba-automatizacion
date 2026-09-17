"""Orquestación del proceso completo y persistencia.

Idempotente: ejecutar dos veces con las mismas entradas produce exactamente
el mismo resultado. La deduplicación de correos es por message_id, así que
reincorporar un lote ya procesado no duplica nada.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pandas as pd

from . import casos as mcasos
from . import correos as mcorreos
from .config import (CORTE_ACTUALIZACION, CORTE_INICIAL, DATASETS, DIR_DATOS,
                     LOTE_ACTUALIZACION, RUTA_DB)
from .ingesta import cargar_correos, cargar_pedidos

TABLAS = ("lineas", "correos_analizados", "accionables", "requiere_decision", "metricas")


def ejecutar(dataset: str = "muestra", con_actualizacion: bool = False,
             db: Path = RUTA_DB) -> dict:
    t0 = time.perf_counter()
    cfg = DATASETS[dataset]

    rutas_correo = [DIR_DATOS / n for n in cfg["correos"]]
    if con_actualizacion:
        rutas_correo.append(DIR_DATOS / LOTE_ACTUALIZACION)
    corte_dt = CORTE_ACTUALIZACION if con_actualizacion else CORTE_INICIAL
    corte = corte_dt.date()
    # Los ficheros no llevan zona horaria; el corte es hora de Madrid.
    corte_ts = pd.Timestamp(corte_dt).tz_localize(None)

    t = time.perf_counter()
    lineas, clientes, m_ped = cargar_pedidos(DIR_DATOS / cfg["pedidos"])
    correos, m_cor = cargar_correos(rutas_correo, corte_ts)
    t_ingesta = time.perf_counter() - t

    emails = {
        str(e).lower(): c
        for c, e in zip(clientes["cliente_id"], clientes["email"])
        if pd.notna(e)
    }

    t = time.perf_counter()
    analisis = mcorreos.analizar(correos, emails)
    analisis = mcasos.cruce_difuso(analisis, lineas)
    analisis = mcasos.marcar_verificacion(analisis, clientes, lineas)
    t_parseo = time.perf_counter() - t

    t = time.perf_counter()
    desde = pd.Timestamp(CORTE_INICIAL).tz_localize(None) if con_actualizacion else None
    acc, req = mcasos.construir_casos(lineas, analisis, clientes, corte, desde)
    t_cruce = time.perf_counter() - t

    metricas = {
        "dataset": dataset,
        "con_actualizacion": int(con_actualizacion),
        "corte": corte_ts.strftime("%d/%m/%Y %H:%M"),
        **{f"pedidos_{k}": v for k, v in m_ped.items()},
        **{f"correos_{k}": v for k, v in m_cor.items()},
        "casos_accionables": len(acc),
        "casos_nuevos_del_lote": int(acc["novedad"].sum()),
        "casos_requiere_decision": len(req),
        "correos_en_cuarentena": int((~analisis["verificado"] & analisis["pedido_id"].notna()).sum()),
        "correos_sin_accion": int(analisis["intencion"].eq("sin_accion").sum()),
        "correos_no_clasificados": int(analisis["intencion"].eq("no_clasificado").sum()),
        "rectificaciones": int(analisis["rectifica_a"].notna().sum()),
        "anulados_por_rectificacion": int(analisis["anulado_por_rectificacion"].sum()),
        "t_ingesta_s": round(t_ingesta, 3),
        "t_parseo_s": round(t_parseo, 3),
        "t_cruce_s": round(t_cruce, 3),
        "t_total_s": round(time.perf_counter() - t0, 3),
    }

    _guardar(db, lineas, analisis, acc, req, metricas)
    return {"metricas": metricas, "accionables": acc, "requiere_decision": req,
            "analisis": analisis, "lineas": lineas}


def _guardar(db, lineas, analisis, acc, req, metricas):
    con = sqlite3.connect(db)
    try:
        for t in TABLAS:
            con.execute(f"DROP TABLE IF EXISTS {t}")
        lineas.to_sql("lineas", con, index=False)
        analisis.astype(str).to_sql("correos_analizados", con, index=False)
        acc.astype(str).to_sql("accionables", con, index=False)
        (req if not req.empty else pd.DataFrame([{"motivo": None}])).astype(str).to_sql(
            "requiere_decision", con, index=False)
        pd.DataFrame([metricas]).to_sql("metricas", con, index=False)
        con.commit()
    finally:
        con.close()
