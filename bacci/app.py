"""API local y servidor de la pantalla de operaciones."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .pipeline import ejecutar

app = FastAPI(title="Control de pedidos · Bacci")
ESTATICO = Path(__file__).parent / "static"

_estado: dict = {"resultado": None}
# Marcas de gestión propias de esta herramienta (no del ERP).
_revisados: set[str] = set()


class Peticion(BaseModel):
    dataset: str = "muestra"
    con_actualizacion: bool = False


class Marca(BaseModel):
    caso_id: str
    revisado: bool


def _limpio(v):
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NaT:
        return None
    if isinstance(v, (pd.Timestamp,)):
        return str(v)
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            return str(v)
    if pd.isna(v) if not isinstance(v, (list, dict)) else False:
        return None
    return v


def _registros(df: pd.DataFrame, cols: list[str]) -> list[dict]:
    if df.empty:
        return []
    return [
        {c: _limpio(r.get(c)) for c in cols if c in df.columns}
        for r in df.to_dict("records")
    ]


@app.get("/")
def raiz():
    return FileResponse(ESTATICO / "index.html")


@app.post("/api/procesar")
def procesar(p: Peticion):
    _estado["resultado"] = ejecutar(p.dataset, p.con_actualizacion)
    return {"metricas": _estado["resultado"]["metricas"]}


@app.get("/api/casos")
def casos():
    r = _estado["resultado"]
    if r is None:
        return {"procesado": False}

    acc = r["accionables"].copy()
    acc["caso_id"] = acc["pedido_id"] + "/" + acc["linea_id"].astype(str)
    acc["revisado"] = acc["caso_id"].isin(_revisados)

    cols_acc = [
        "caso_id", "pedido_id", "linea_id", "cliente_id", "cliente", "sku",
        "color", "talla", "uds_pedidas", "uds_enviadas", "uds_pendientes",
        "precio_unitario_eur", "fecha_compromiso", "dias_al_compromiso",
        "intencion", "fecha_solicitada", "motivo", "accion_propuesta",
        "puntuacion", "pts_fecha", "pts_peticion", "pts_volumen",
        "conflicto_uds", "uds_pedidas_min", "uds_pedidas_max", "sobreservido",
        "sin_fecha", "message_id", "revisado", "ya_servida", "novedad",
    ]

    an = r["analisis"]
    corr = an[an["pedido_id"].notna() & an["linea_id"].notna()].copy()
    corr["caso_id"] = corr["pedido_id"] + "/" + corr["linea_id"].astype(str)
    cols_cor = ["caso_id", "message_id", "received_at", "remitente", "subject",
                "body", "intencion", "fecha_solicitada", "verificado",
                "anulado_por_rectificacion", "rectifica_a", "origen_cruce"]

    return {
        "procesado": True,
        "metricas": r["metricas"],
        "accionables": _registros(acc, cols_acc),
        "requiere_decision": _registros(
            r["requiere_decision"],
            ["motivo", "accion_propuesta", "message_id", "received_at",
             "remitente", "cliente", "pedido_id", "linea_id", "subject",
             "body", "email_registrado", "candidatos"],
        ),
        "correos": _registros(corr, cols_cor),
        "clientes": sorted(acc["cliente"].dropna().unique().tolist()),
    }


@app.post("/api/marcar")
def marcar(m: Marca):
    """Estado de gestión propio de la app. NO modifica el ERP."""
    _revisados.add(m.caso_id) if m.revisado else _revisados.discard(m.caso_id)
    return {"caso_id": m.caso_id, "revisado": m.caso_id in _revisados}
