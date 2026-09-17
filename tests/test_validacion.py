"""Validación: esperado vs obtenido.

Los valores esperados están calculados a mano sobre los ficheros originales
(ver README, sección Validación). Si el pipeline cambia y estos tests pasan
igual, es que el cambio no ha roto la lógica de negocio.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from bacci.config import DIR_DATOS
from bacci.correos import clasificar, extraer_fecha_solicitada, extraer_referencias
from bacci.ingesta import cargar_correos, cargar_pedidos
from bacci.pipeline import ejecutar


# --- Nivel 1: la ingesta no inventa ni pierde datos --------------------------

def test_conteos_crudos_coinciden_con_el_excel():
    crudo = pd.read_excel(DIR_DATOS / "Pedidos_full.xlsx", sheet_name="Pedidos")
    assert len(crudo) == 20_000
    lineas, clientes, m = cargar_pedidos(DIR_DATOS / "Pedidos_full.xlsx")
    assert len(clientes) == 250
    # 20.000 filas - 400 copias exactas - 200 claves en conflicto colapsadas
    assert m["duplicados_exactos"] == 400
    assert m["claves_en_conflicto"] == 200
    assert m["lineas_unicas"] == 19_400
    assert len(lineas) == 19_400
    # La clave compuesta es única tras normalizar.
    assert not lineas.duplicated(["pedido_id", "linea_id"]).any()


def test_anomalias_detectadas_en_pedidos():
    _, _, m = cargar_pedidos(DIR_DATOS / "Pedidos_full.xlsx")
    assert m["sobreservidas"] == 100      # uds_enviadas > uds_pedidas
    assert m["sin_fecha"] == 200
    assert m["sin_precio"] == 60
    assert m["cliente_huerfano"] == 40


def test_pendiente_nunca_negativo_y_suma_coherente():
    lineas, _, _ = cargar_pedidos(DIR_DATOS / "Pedidos_full.xlsx")
    assert (lineas["uds_pendientes"] >= 0).all()
    normales = lineas[~lineas["sobreservido"]]
    esperado = (normales["uds_pedidas"] - normales["uds_enviadas"]).sum()
    assert normales["uds_pendientes"].sum() == esperado


def test_conflicto_toma_el_mayor_y_queda_marcado():
    """P-26009/10000 aparece con 500 y con 450 unidades pedidas."""
    lineas, _, _ = cargar_pedidos(DIR_DATOS / "Pedidos_full.xlsx")
    f = lineas[(lineas.pedido_id == "P-26009") & (lineas.linea_id == 10000)].iloc[0]
    assert f["uds_pedidas"] == 500          # criterio: el mayor
    assert f["conflicto_uds"]               # y queda marcado para revisión
    assert f["uds_pedidas_min"] == 450
    assert f["uds_pedidas_max"] == 500
    assert f["uds_pendientes"] == 400       # 500 - 100, calculado a mano


def test_correos_deduplicados_por_message_id():
    _, m = cargar_correos([DIR_DATOS / "Correos_full.xlsx"])
    assert m["filas_origen"] == 4_000
    assert m["reentregas_descartadas"] == 200
    assert m["correos_unicos"] == 3_800


# --- Nivel 2: interpretación del texto ---------------------------------------

@pytest.mark.parametrize("texto,esperado", [
    ("Necesitamos mover la fecha de P-31868 / 20000 al 21/09/2026.", [("P-31868", 20000)]),
    ("¿Tenéis alguna actualización de la línea 20000 de P-32677?", [("P-32677", 20000)]),
    ("Estado de P-30388, línea 50000, y P-31138, línea 20000.",
     [("P-30388", 50000), ("P-31138", 20000)]),
    # El número del propio pedido no es un número de línea.
    ("Consultamos el estado de P-30431.", [("P-30431", None)]),
])
def test_extraccion_de_referencias(texto, esperado):
    refs, _ = extraer_referencias(texto)
    assert sorted((r["pedido_id"], r["linea_id"]) for r in refs) == sorted(esperado)


def test_asunto_y_cuerpo_son_un_solo_caso():
    """El pedido citado en el asunto sin línea y en el cuerpo con línea
    no debe generar dos casos."""
    texto = "Solicitud de entrega P-31868 | Mover P-31868 / 20000 al 21/09/2026."
    refs, _ = extraer_referencias(texto)
    assert refs == [{"pedido_id": "P-31868", "linea_id": 20000}]


def test_el_id_de_mensaje_citado_no_es_un_numero_de_linea():
    """'Rectifico mi correo msg-10020' no debe leerse como línea 10020."""
    refs, _ = extraer_referencias(
        "Rectifico mi correo msg-10020. Para P-31114, línea 20000, solicitamos el 23/09/2026."
    )
    assert refs == [{"pedido_id": "P-31114", "linea_id": 20000}]


def test_referencia_con_formato_invalido_se_aisla():
    refs, invalidos = extraer_referencias("¿Podéis comprobar P-X003656, línea 10000?")
    assert refs == []
    assert invalidos == ["P-X003656"]


@pytest.mark.parametrize("texto,esperado", [
    ("Necesitamos cancelar P-31860, línea 30000.", "cancelacion"),
    ("¿Podéis adelantar la entrega del artículo PAN-102?", "adelanto"),
    ("Para P-26002 solicitamos cambiar la fecha al 16/09/2026.", "cambio_fecha"),
    ("¿Podéis informar del estado de P-26004?", "consulta_estado"),
    ("Gracias por la información. Mantenemos lo acordado; no solicitamos cambios.", "sin_accion"),
    # Niega el cambio pero sigue pidiendo información: hay que responder.
    ("¿Nos informáis del estado de P-26004? No estamos solicitando cambiarla.", "consulta_estado"),
])
def test_clasificacion_de_intencion(texto, esperado):
    assert clasificar(texto) == esperado


def test_fecha_solicitada():
    assert extraer_fecha_solicitada("nueva fecha 21/09/2026") == date(2026, 9, 21)
    assert extraer_fecha_solicitada("sin fecha alguna") is None


def test_todos_los_correos_quedan_clasificados():
    """Si aparecen correos no clasificados, hay un patrón nuevo que revisar."""
    r = ejecutar("full")
    assert r["metricas"]["correos_no_clasificados"] == 0


def test_el_corte_descarta_correos_posteriores():
    """El lote de actualización llega entre las 10:00 y las 11:00: con el corte
    inicial no debe verse, con el de actualización sí."""
    from bacci.config import CORTE_ACTUALIZACION, CORTE_INICIAL, LOTE_ACTUALIZACION

    rutas = [DIR_DATOS / "Correos_full.xlsx", DIR_DATOS / LOTE_ACTUALIZACION]
    diez = pd.Timestamp(CORTE_INICIAL).tz_localize(None)
    once = pd.Timestamp(CORTE_ACTUALIZACION).tz_localize(None)

    _, m10 = cargar_correos(rutas, diez)
    _, m11 = cargar_correos(rutas, once)

    assert m10["posteriores_al_corte"] == 4   # 4 de las 5 filas son posteriores
    assert m11["posteriores_al_corte"] == 0
    assert m11["correos_unicos"] > m10["correos_unicos"]


def test_cancelacion_sobre_linea_ya_servida_no_se_pierde():
    """Las cancelaciones caen sobre líneas servidas al 100%: si el carril
    accionable solo admitiera líneas con pendiente, desaparecerían."""
    acc = ejecutar("full")["accionables"]
    can = acc[acc["intencion"] == "cancelacion"]
    assert len(can) == 183
    assert can["ya_servida"].all()
    assert can["accion_propuesta"].str.contains("devolución o abono").all()


# --- Nivel 3: cruce, verificación y prioridad --------------------------------

def test_remitente_no_registrado_queda_en_cuarentena():
    r = ejecutar("full")
    req = r["requiere_decision"]
    cuarentena = req[req["motivo"].str.contains("CUARENTENA")]
    assert len(cuarentena) == 191
    # 190 son direcciones externas ("soy el nuevo contacto"); 1 es un cliente
    # registrado preguntando por una línea que no es suya.
    assert cuarentena["remitente"].str.contains("externo").sum() == 190


def test_una_peticion_en_cuarentena_no_llega_a_los_accionables():
    r = ejecutar("full")
    cuar = set(
        r["analisis"].loc[~r["analisis"]["verificado"], "message_id"]
    )
    usados = set(r["accionables"]["message_id"].dropna())
    assert not (cuar & usados)


def test_rectificacion_encadenada_deja_vigente_la_ultima():
    """msg-001 pide el 16/09, msg-002 lo rectifica al 12/09 (corte 10:00).
    El lote de actualización añade msg-20001, que rectifica al 13/09."""
    antes = ejecutar("full")["accionables"]
    despues = ejecutar("full", con_actualizacion=True)["accionables"]

    a = antes[(antes.pedido_id == "P-26002") & (antes.linea_id == 10000)].iloc[0]
    d = despues[(despues.pedido_id == "P-26002") & (despues.linea_id == 10000)].iloc[0]
    assert a["fecha_solicitada"] == date(2026, 9, 12)
    assert d["fecha_solicitada"] == date(2026, 9, 13)


def test_puntuacion_es_la_suma_de_los_tres_kpis():
    acc = ejecutar("muestra")["accionables"]
    suma = acc["pts_fecha"] + acc["pts_peticion"] + acc["pts_volumen"]
    assert (acc["puntuacion"] == suma).all()
    assert acc["puntuacion"].between(0, 100).all()


def test_entran_pendientes_y_servidas_con_peticion_viva():
    """Una cancelación sobre una línea ya servida no puede desaparecer:
    sigue exigiendo respuesta (devolución o abono)."""
    r = ejecutar("full")
    acc = r["accionables"]
    servidas = acc[acc["ya_servida"]]
    # Las ya servidas solo entran si el cliente pide algo.
    assert (servidas["intencion"] != "sin_correo").all()
    assert (servidas["pts_volumen"] == 0).all()
    # Las 190 cancelaciones del fichero caen sobre líneas ya servidas.
    assert (acc["intencion"] == "cancelacion").sum() == 183
    # Y el resto de la lista sí tiene pendiente.
    assert (acc[~acc["ya_servida"]]["uds_pendientes"] > 0).all()


def test_cruce_difuso_solo_enlaza_cuando_es_unico():
    an = ejecutar("full")["analisis"]
    ambiguos = an[an["origen_cruce"] == "difuso_ambiguo"]
    # Los ambiguos no se enlazan: se dejan para decisión humana.
    assert ambiguos["candidatos_difusos"].notna().all()
    assert len(ambiguos) == 16
    assert (an["origen_cruce"] == "difuso_unico").sum() == 362


# --- Nivel 4: idempotencia y prueba de actualización -------------------------

COLS = ["pedido_id", "linea_id", "uds_pendientes", "intencion",
        "fecha_solicitada", "puntuacion"]


def _firma(r):
    return (r["accionables"][COLS]
            .sort_values(["pedido_id", "linea_id"])
            .reset_index(drop=True))


def test_dos_ejecuciones_iguales_dan_el_mismo_resultado():
    assert _firma(ejecutar("full")).equals(_firma(ejecutar("full")))


def test_el_lote_marca_los_casos_nuevos():
    r = ejecutar("full", con_actualizacion=True)
    assert r["metricas"]["casos_nuevos_del_lote"] == 2
    nuevos = r["accionables"][r["accionables"]["novedad"]]
    assert set(nuevos["pedido_id"]) == {"P-26002", "P-26004"}


def test_incorporar_el_lote_no_duplica_correos():
    base = ejecutar("full")["metricas"]["correos_correos_unicos"]
    tras = ejecutar("full", con_actualizacion=True)["metricas"]["correos_correos_unicos"]
    # 5 filas nuevas: msg-20002, msg-20003 y msg-20001 (duplicado en el lote),
    # más msg-001 que ya existía. Solo entran 3 mensajes nuevos.
    assert base == 3_800
    assert tras == 3_803


def test_repetir_la_incorporacion_no_altera_nada():
    uno = ejecutar("full", con_actualizacion=True)
    dos = ejecutar("full", con_actualizacion=True)
    assert _firma(uno).equals(_firma(dos))
    assert (uno["metricas"]["correos_correos_unicos"]
            == dos["metricas"]["correos_correos_unicos"])
