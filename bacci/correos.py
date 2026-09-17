"""Interpretación del texto de los correos.

Determinista a propósito: el lenguaje está plantillado, así que reglas dan
resultados reproducibles y auditables. Lo que NO encaja en un patrón no se
adivina: se marca `no_clasificado` y va al carril de revisión humana.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd

RE_PEDIDO = re.compile(r"\bP-[A-Za-z0-9]+\b")
RE_PEDIDO_VALIDO = re.compile(r"^P-\d+$")
RE_LINEA = re.compile(r"\b\d{5}\b")
RE_FECHA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
RE_RECTIFICA = re.compile(r"rectifico mi correo\s+(msg-[A-Za-z0-9]+)", re.I)
RE_MSGID = re.compile(r"\bmsg-[A-Za-z0-9]+\b", re.I)
RE_ARTICULO = re.compile(
    r"art[ií]culo\s+([A-Z]{2,4}-\d{3})[,\s]+color\s+(\w+)[,\s]+talla\s+(\w+)", re.I
)

VENTANA_PAREJA = 60      # caracteres máximos entre "P-xxxxx" y su número de línea
PENALIZACION_INVERSA = 40  # coste extra si la línea precede al pedido

# El orden importa: lo que anula acción se evalúa primero.
# Acuse puro: no pide nada en absoluto.
SENALES_ACUSE = (
    "solo un acuse",
    "mantenemos lo acordado",
    "mantenemos la fecha",
)
# Niega un cambio de fecha, pero puede seguir pidiendo información.
SENALES_NIEGA_CAMBIO = (
    "no solicitamos",
    "no estamos solicitando",
)
SENALES_ESTADO = (
    "estado",
    "actualización",
    "actualizacion",
    "seguimos pendientes",
    "unidades faltan",
    "faltan por servir",
    "revisad",
    "según lo previsto",
    "segun lo previsto",
    "confirmar qué unidades",
    "confirmar que unidades",
)


def texto_completo(fila) -> str:
    """El pedido puede venir en el asunto, en el cuerpo o en ambos."""
    return f"{fila['subject']} | {fila['body']}"


def extraer_referencias(texto: str) -> tuple[list[dict], list[str]]:
    """Empareja cada P-xxxxx con el número de línea más próximo.

    Devuelve (referencias, pedidos_con_formato_invalido).
    """
    pedidos = [(m.group(0), m.start()) for m in RE_PEDIDO.finditer(texto)]

    # "P-30431" y "msg-10020" contienen números de 5 dígitos que NO son
    # líneas: se enmascaran (conservando posiciones) antes de buscar líneas.
    masc = list(texto)
    for patron in (RE_PEDIDO, RE_MSGID):
        for m in patron.finditer(texto):
            for i in range(m.start(), m.end()):
                masc[i] = "·"
    enmascarado = "".join(masc)
    lineas = [(int(m.group(0)), m.start()) for m in RE_LINEA.finditer(enmascarado)]

    invalidos = sorted({p for p, _ in pedidos if not RE_PEDIDO_VALIDO.match(p)})
    validos = [(p, i) for p, i in pedidos if RE_PEDIDO_VALIDO.match(p)]

    # Emparejado voraz por distancia: resuelve tanto "P-X / 40000"
    # como "la línea 20000 de P-X".
    # La línea normalmente sigue al pedido ("P-X / 40000", "P-X, línea 40000").
    # El orden inverso existe ("la línea 40000 de P-X") pero es menos fiable,
    # así que se penaliza: sin esto, en un correo con dos pedidos la línea del
    # segundo puede acabar asignada al primero por pura cercanía.
    candidatos = sorted(
        (
            (abs(pi - li) + (0 if li > pi else PENALIZACION_INVERSA), p, ln, pi, li)
            for p, pi in validos
            for ln, li in lineas
            if abs(pi - li) <= VENTANA_PAREJA
        )
    )
    pedidos_usados: set[int] = set()
    lineas_usadas: set[int] = set()
    parejas: dict[int, int] = {}
    for _, _p, ln, pi, li in candidatos:
        if pi in pedidos_usados or li in lineas_usadas:
            continue
        pedidos_usados.add(pi)
        lineas_usadas.add(li)
        parejas[pi] = ln

    # Un mismo pedido puede citarse en el asunto (sin línea) y en el cuerpo
    # (con línea): es UN caso, no dos. Si hay línea, manda la versión con línea.
    por_pedido: dict[str, set] = {}
    for p, pi in validos:
        por_pedido.setdefault(p, set()).add(parejas.get(pi))

    refs = []
    for p, lns in por_pedido.items():
        concretas = {l for l in lns if l is not None}
        for l in sorted(concretas) if concretas else [None]:
            refs.append({"pedido_id": p, "linea_id": l})
    return refs, invalidos


def extraer_fecha_solicitada(texto: str, hoy: date | None = None) -> date | None:
    m = RE_FECHA.search(texto)
    if not m:
        return None
    d, mo, a = (int(x) for x in m.groups())
    try:
        return date(a, mo, d)
    except ValueError:
        return None


def clasificar(texto: str) -> str:
    t = texto.lower()
    pide_estado = any(s in t for s in SENALES_ESTADO)

    # "solo un acuse" es decisivo: el cliente declara que no pide nada,
    # aunque mencione que sigue esperando confirmación.
    if "solo un acuse" in t:
        return "sin_accion"
    if any(s in t for s in SENALES_ACUSE) and not pide_estado:
        return "sin_accion"
    # "No solicitamos cambio" no implica que no pida nada: puede pedir estado.
    if any(s in t for s in SENALES_NIEGA_CAMBIO):
        return "consulta_estado" if pide_estado else "sin_accion"

    if "cancelar" in t or "cancelación" in t or "cancelacion" in t:
        return "cancelacion"
    if "adelantar" in t or "adelanto" in t:
        return "adelanto"
    if RE_FECHA.search(texto) and any(
        s in t
        for s in (
            "nueva fecha",
            "solicitamos el",
            "cambiar la fecha",
            "mover la fecha",
            "proponemos",
            "ajustar",
            "solicitamos entrega",
            "solicitamos la entrega",
            "puede recibir",
            "fecha solicitada",
            "cambiad",
            "solicitamos cambiar",
            "comprobar",
        )
    ):
        return "cambio_fecha"
    if pide_estado:
        return "consulta_estado"
    return "no_clasificado"


def analizar(correos: pd.DataFrame, emails_cliente: dict[str, str]) -> pd.DataFrame:
    """Un registro por (correo, referencia). Los correos sin referencia válida
    también salen, con `pedido_id` nulo, para no perderlos."""
    filas = []
    for _, c in correos.iterrows():
        texto = texto_completo(c)
        refs, invalidos = extraer_referencias(texto)
        rect = RE_RECTIFICA.search(texto)
        art = RE_ARTICULO.search(texto)
        base = {
            "message_id": c["message_id"],
            "received_at": c["received_at"],
            "remitente": c["from"],
            "subject": c["subject"],
            "body": c["body"],
            "intencion": clasificar(texto),
            "fecha_solicitada": extraer_fecha_solicitada(texto),
            "rectifica_a": rect.group(1) if rect else None,
            "pedido_invalido": ";".join(invalidos) or None,
            "cliente_id": emails_cliente.get(c["from"]),
            "sku": art.group(1).upper() if art else None,
            "color": art.group(2).capitalize() if art else None,
            "talla": art.group(3).upper() if art else None,
        }
        if refs:
            for r in refs:
                filas.append({**base, **r})
        else:
            filas.append({**base, "pedido_id": None, "linea_id": None})

    df = pd.DataFrame(filas)
    # Int64 (nullable) para que el merge con las líneas cruce por tipo.
    df["linea_id"] = df["linea_id"].astype("Int64")

    # Una rectificación anula al mensaje que cita.
    anulados = set(df["rectifica_a"].dropna())
    df["anulado_por_rectificacion"] = df["message_id"].isin(anulados)
    return df
