"""Cruce, verificación y priorización.

Dos carriles de salida:
  - ACCIONABLE: líneas con pendiente, ordenadas por puntuación 0-100.
  - REQUIERE DECISIÓN: lo que el sistema no puede resolver solo. Sin
    puntuación (no es "menos urgente", es que está bloqueado); ordenado
    por antigüedad para que no se pudra.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .config import PESO_FECHA, PESO_PETICION, PESO_VOLUMEN

SIN_ACCION = {"sin_accion"}


# --- Verificación de remitente -----------------------------------------------

def marcar_verificacion(analisis: pd.DataFrame, clientes: pd.DataFrame,
                        lineas: pd.DataFrame) -> pd.DataFrame:
    """Un correo está verificado si su remitente es el contacto registrado
    del cliente dueño de la línea. Si no, CUARENTENA: se registra, no se aplica.
    """
    dueño = lineas[["pedido_id", "linea_id", "cliente_id"]].drop_duplicates()
    df = analisis.merge(
        dueño.rename(columns={"cliente_id": "cliente_linea"}),
        on=["pedido_id", "linea_id"],
        how="left",
    )
    emails = clientes.set_index("cliente_id")["email"].to_dict()
    df["email_registrado"] = df["cliente_linea"].map(emails)
    df["verificado"] = (
        df["email_registrado"].notna()
        & (df["remitente"].str.lower() == df["email_registrado"].str.lower())
    )
    df.loc[df["cliente_linea"].isna(), "verificado"] = False
    return df


# --- Cruce difuso por artículo ------------------------------------------------

def cruce_difuso(analisis: pd.DataFrame, lineas: pd.DataFrame) -> pd.DataFrame:
    """Correos sin referencia de pedido pero con SKU+color+talla.

    Enlaza solo si el resultado es ÚNICO. Si hay varios candidatos, se listan
    para que una persona elija. Si no hay ninguno, queda sin resolver.
    """
    pendientes = lineas[lineas["uds_pendientes"] > 0]
    sin_ref = analisis["pedido_id"].isna() & analisis["sku"].notna()

    analisis["candidatos_difusos"] = None
    analisis["origen_cruce"] = np.where(analisis["pedido_id"].notna(), "referencia", None)

    for i in analisis.index[sin_ref]:
        f = analisis.loc[i]
        if not f["cliente_id"]:
            continue
        c = pendientes[
            (pendientes["cliente_id"] == f["cliente_id"])
            & (pendientes["sku"] == f["sku"])
            & (pendientes["color"].str.capitalize() == f["color"])
            & (pendientes["talla"].str.upper() == f["talla"])
        ]
        etiquetas = [f"{r.pedido_id}/{r.linea_id}" for r in c.itertuples()]
        if len(c) == 1:
            analisis.at[i, "pedido_id"] = c.iloc[0]["pedido_id"]
            analisis.at[i, "linea_id"] = int(c.iloc[0]["linea_id"])
            analisis.at[i, "origen_cruce"] = "difuso_unico"
        elif len(c) > 1:
            analisis.at[i, "candidatos_difusos"] = ";".join(etiquetas)
            analisis.at[i, "origen_cruce"] = "difuso_ambiguo"
        else:
            analisis.at[i, "origen_cruce"] = "difuso_sin_match"
    return analisis


# --- Petición vigente por línea ----------------------------------------------

def peticion_vigente(analisis: pd.DataFrame) -> pd.DataFrame:
    """Por línea, la última petición válida: no anulada por rectificación,
    verificada, que pida algo y con referencia resuelta."""
    v = analisis[
        analisis["pedido_id"].notna()
        & analisis["linea_id"].notna()
        & ~analisis["anulado_por_rectificacion"]
        & analisis["verificado"]
        & ~analisis["intencion"].isin(SIN_ACCION)
        & (analisis["intencion"] != "no_clasificado")
    ]
    if v.empty:
        return pd.DataFrame(
            columns=["pedido_id", "linea_id", "intencion", "fecha_solicitada",
                     "message_id", "received_at"]
        )
    # idxmax, no groupby().last(): este último toma el último valor NO NULO
    # de cada columna por separado y mezclaría dos correos distintos.
    idx = v.groupby(["pedido_id", "linea_id"])["received_at"].idxmax()
    return v.loc[idx, ["pedido_id", "linea_id", "intencion", "fecha_solicitada",
                       "message_id", "received_at"]].reset_index(drop=True)


# --- Puntuación ---------------------------------------------------------------

def _puntos_fecha(f, corte: date) -> int:
    if pd.isna(f):
        return PESO_FECHA["sin_fecha"]
    d = (f.date() - corte).days
    if d < -7:
        return PESO_FECHA["vencida_mas_7d"]
    if d < 0:
        return PESO_FECHA["vencida_1_7d"]
    if d == 0:
        return PESO_FECHA["vence_hoy"]
    if d <= 3:
        return PESO_FECHA["vence_1_3d"]
    if d <= 14:
        return PESO_FECHA["vence_4_14d"]
    return PESO_FECHA["vence_mas_14d"]


def _puntos_volumen(serie: pd.Series) -> pd.Series:
    pct = serie.rank(pct=True) * 100
    out = pd.Series(PESO_VOLUMEN[-1][1], index=serie.index)
    for umbral, puntos in PESO_VOLUMEN:
        out = out.mask(pct >= umbral, puntos)
    return out


def construir_casos(lineas: pd.DataFrame, analisis: pd.DataFrame,
                    clientes: pd.DataFrame, corte: date,
                    desde: pd.Timestamp | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    vig = peticion_vigente(analisis)

    # Entran las líneas con pendiente, y también las ya servidas por completo
    # sobre las que el cliente tiene una petición viva: una cancelación sobre
    # material ya enviado sigue exigiendo respuesta (devolución o abono).
    con_peticion = set(zip(vig["pedido_id"], vig["linea_id"]))
    tiene_peticion = pd.Series(
        [(p, l) in con_peticion
         for p, l in zip(lineas["pedido_id"], lineas["linea_id"])],
        index=lineas.index,
    )
    acc = lineas[(lineas["uds_pendientes"] > 0) | tiene_peticion].merge(
        vig, on=["pedido_id", "linea_id"], how="left"
    )
    acc["intencion"] = acc["intencion"].fillna("sin_correo")
    acc["ya_servida"] = acc["uds_pendientes"] == 0

    acc["pts_fecha"] = acc["fecha_compromiso"].apply(lambda f: _puntos_fecha(f, corte))
    acc["pts_peticion"] = acc["intencion"].map(PESO_PETICION).fillna(0).astype(int)
    acc["pts_volumen"] = _puntos_volumen(acc["uds_pendientes"]).astype(int)
    acc.loc[acc["ya_servida"], "pts_volumen"] = 0  # nada que expedir
    acc["puntuacion"] = acc["pts_fecha"] + acc["pts_peticion"] + acc["pts_volumen"]

    acc["dias_al_compromiso"] = acc["fecha_compromiso"].apply(
        lambda f: None if pd.isna(f) else (f.date() - corte).days
    )
    # Peticiones que han entrado con el último lote: se marcan para que
    # operaciones vea de un vistazo qué ha cambiado desde la ejecución anterior.
    acc["novedad"] = (
        acc["received_at"] > desde if desde is not None else False
    )
    acc["motivo"] = acc.apply(_motivo, axis=1)
    acc["accion_propuesta"] = acc.apply(_accion, axis=1)

    nombres = clientes.set_index("cliente_id")["nombre"].to_dict()
    acc["cliente"] = acc["cliente_id"].map(nombres).fillna("(no está en el maestro)")

    acc = acc.sort_values("puntuacion", ascending=False).reset_index(drop=True)
    return acc, _requiere_decision(lineas, analisis, clientes)


def _motivo(r) -> str:
    partes = []
    d = r["dias_al_compromiso"]
    if d is None or pd.isna(d):
        partes.append("sin fecha comprometida")
    elif d < 0:
        partes.append(f"vencida hace {abs(int(d))} d")
    elif d == 0:
        partes.append("vence hoy")
    else:
        partes.append(f"vence en {int(d)} d")
    if r["ya_servida"]:
        partes.append("ya servida en su totalidad")
    else:
        partes.append(f"{int(r['uds_pendientes'])} uds pendientes")
    if r["intencion"] != "sin_correo":
        partes.append(f"cliente: {r['intencion'].replace('_', ' ')}")
    if r["conflicto_uds"]:
        partes.append("⚠ uds en conflicto")
    if r["sobreservido"]:
        partes.append("⚠ sobreservido")
    return " · ".join(partes)


def _accion(r) -> str:
    if r["intencion"] == "cancelacion":
        if r["ya_servida"]:
            return ("La línea ya se sirvió por completo: gestionar devolución o "
                    "abono con el cliente, no cancelación")
        return "Confirmar si aún es posible cancelar y parar producción/expedición"
    if r["intencion"] == "adelanto":
        f = r["fecha_solicitada"]
        return f"Revisar viabilidad de adelanto{f' a {f}' if f else ''} y responder"
    if r["intencion"] == "cambio_fecha":
        f = r["fecha_solicitada"]
        return f"Confirmar o rechazar nueva fecha{f' ({f})' if f else ''} en el ERP"
    if r["intencion"] == "consulta_estado":
        return "Responder al cliente con el estado y las unidades pendientes"
    if r["ya_servida"]:
        return "Responder al cliente: la línea ya se sirvió por completo"
    d = r["dias_al_compromiso"]
    if d is not None and not pd.isna(d) and d < 0:
        return "Expedir o renegociar: compromiso incumplido"
    return "Programar expedición antes del compromiso"


def _requiere_decision(lineas, analisis, clientes) -> pd.DataFrame:
    nombres = clientes.set_index("cliente_id")["nombre"].to_dict()
    filas = []

    def add(r, motivo, accion):
        filas.append({
            "motivo": motivo,
            "accion_propuesta": accion,
            "message_id": r.get("message_id"),
            "received_at": r.get("received_at"),
            "remitente": r.get("remitente"),
            "cliente": nombres.get(r.get("cliente_linea") or r.get("cliente_id"), "—"),
            "pedido_id": r.get("pedido_id"),
            "linea_id": r.get("linea_id"),
            "subject": r.get("subject"),
            "body": r.get("body"),
            "email_registrado": r.get("email_registrado"),
            "candidatos": r.get("candidatos_difusos"),
        })

    for _, r in analisis.iterrows():
        if r["intencion"] in SIN_ACCION:
            continue
        if pd.notna(r["pedido_invalido"]) and r["pedido_invalido"]:
            add(r, f"Referencia con formato inválido ({r['pedido_invalido']})",
                "Confirmar la referencia correcta con el cliente")
        elif r["origen_cruce"] == "difuso_ambiguo":
            add(r, "Artículo sin referencia de pedido: varias líneas encajan",
                "Elegir la línea correcta entre los candidatos")
        elif r["origen_cruce"] == "difuso_sin_match":
            add(r, "Artículo sin referencia y sin línea pendiente que encaje",
                "Verificar con el cliente; puede ser un pedido no dado de alta")
        elif pd.isna(r["pedido_id"]):
            add(r, "Correo sin referencia de pedido identificable",
                "Leer y clasificar manualmente")
        elif not r["verificado"]:
            add(r, "Remitente no registrado para este cliente (CUARENTENA)",
                "Verificar identidad con el contacto del maestro antes de aplicar. "
                "Nunca responder al remitente del correo para confirmar.")
        elif r["intencion"] == "no_clasificado":
            add(r, "Petición no reconocida por las reglas",
                "Leer el correo y decidir")
        elif pd.isna(r["linea_id"]):
            add(r, "Pedido identificado pero sin número de línea",
                "Determinar la línea afectada")

    ok = set(zip(lineas["pedido_id"], lineas["linea_id"]))
    for _, r in analisis[analisis["pedido_id"].notna() & analisis["linea_id"].notna()].iterrows():
        if (r["pedido_id"], r["linea_id"]) not in ok:
            add(r, "La línea citada no existe en la exportación del ERP",
                "Comprobar en Navision si el pedido está dado de alta")

    for _, r in lineas[lineas["cliente_huerfano"]].iterrows():
        filas.append({
            "motivo": "Línea con cliente que no está en el maestro",
            "accion_propuesta": "Dar de alta o corregir el cliente en el ERP",
            "message_id": None, "received_at": None, "remitente": None,
            "cliente": f"({r['cliente_id']})", "pedido_id": r["pedido_id"],
            "linea_id": r["linea_id"], "subject": None, "body": None,
            "email_registrado": None, "candidatos": None,
        })

    df = pd.DataFrame(filas)
    if not df.empty:
        df = df.sort_values("received_at", na_position="last").reset_index(drop=True)
    return df
