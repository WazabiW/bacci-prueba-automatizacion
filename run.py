#!/usr/bin/env python3
"""Ejecuta el proceso por línea de comandos.

  python run.py --dataset full                 proceso normal
  python run.py --dataset full --actualizacion incorpora el lote nuevo
  python run.py --prueba-actualizacion         prueba completa de idempotencia
  python run.py --benchmark                    tiempos con los ficheros completos
"""

from __future__ import annotations

import argparse
import time

from bacci.pipeline import ejecutar

COLS = ["pedido_id", "linea_id", "uds_pendientes", "intencion",
        "fecha_solicitada", "puntuacion"]


def _firma(r):
    import pandas as pd

    f = (r["accionables"][COLS]
         .sort_values(["pedido_id", "linea_id"])
         .reset_index(drop=True))
    # None y NaN representan lo mismo (sin fecha solicitada): se normalizan
    # para que la comparación antes/después no marque cambios falsos.
    f["fecha_solicitada"] = f["fecha_solicitada"].map(
        lambda v: "" if v is None or pd.isna(v) else str(v)
    )
    return f


def _resumen(r) -> None:
    m = r["metricas"]
    print(f"  líneas únicas          {m['pedidos_lineas_unicas']:>7,}"
          f"   (de {m['pedidos_filas_origen']:,} filas)")
    print(f"  correos únicos         {m['correos_correos_unicos']:>7,}"
          f"   ({m['correos_reentregas_descartadas']} reentregas,"
          f" {m['correos_posteriores_al_corte']} tras el corte {m['corte']})")
    print(f"  accionables            {m['casos_accionables']:>7,}")
    print(f"  requieren decisión     {m['casos_requiere_decision']:>7,}")
    print(f"  tiempo total           {m['t_total_s']:>7.2f} s")


def prueba_actualizacion(dataset: str) -> None:
    print(f"PRUEBA DE ACTUALIZACIÓN · {dataset}\n")

    print("1) Proceso inicial (corte 10:00)")
    r1 = ejecutar(dataset)
    _resumen(r1)

    print("\n2) Incorporando Correos_actualizacion.xlsx (corte 11:00)")
    r2 = ejecutar(dataset, con_actualizacion=True)
    _resumen(r2)

    a, b = _firma(r1), _firma(r2)
    comp = a.merge(b, on=["pedido_id", "linea_id"], suffixes=("_antes", "_despues"))
    cambios = comp[
        (comp["intencion_antes"] != comp["intencion_despues"])
        | (comp["puntuacion_antes"] != comp["puntuacion_despues"])
        | (comp["fecha_solicitada_antes"] != comp["fecha_solicitada_despues"])
    ]
    print(f"\n   líneas que cambian: {len(cambios)}")
    for _, c in cambios.iterrows():
        print(f"   · {c['pedido_id']}/{c['linea_id']}: "
              f"{c['intencion_antes']} {c['fecha_solicitada_antes']} → "
              f"{c['intencion_despues']} {c['fecha_solicitada_despues']}")

    print("\n3) Repitiendo la incorporación (dos veces más)")
    r3 = ejecutar(dataset, con_actualizacion=True)
    r4 = ejecutar(dataset, con_actualizacion=True)
    igual = b.equals(_firma(r3)) and b.equals(_firma(r4))
    mismos = (r2["metricas"]["correos_correos_unicos"]
              == r3["metricas"]["correos_correos_unicos"]
              == r4["metricas"]["correos_correos_unicos"])
    print(f"   correos únicos: {r3['metricas']['correos_correos_unicos']:,} "
          f"y {r4['metricas']['correos_correos_unicos']:,} (sin cambio: {mismos})")
    print(f"   resultado idéntico en ambas: {igual}")
    print("\n" + ("OK · el proceso es idempotente" if igual and mismos
                  else "FALLO · la repetición altera el resultado"))


def benchmark(repeticiones: int = 3) -> None:
    print(f"BENCHMARK · ficheros completos · {repeticiones} repeticiones\n")
    tiempos = []
    for i in range(repeticiones):
        t = time.perf_counter()
        r = ejecutar("full")
        tiempos.append(time.perf_counter() - t)
        m = r["metricas"]
        print(f"  {i+1}: {tiempos[-1]:.2f} s   "
              f"(ingesta {m['t_ingesta_s']:.2f} · parseo {m['t_parseo_s']:.2f} "
              f"· cruce {m['t_cruce_s']:.2f})")
    print(f"\n  media {sum(tiempos)/len(tiempos):.2f} s"
          f" · mínimo {min(tiempos):.2f} s · máximo {max(tiempos):.2f} s")
    print("  20.000 pedidos + 4.000 correos")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=["muestra", "full"], default="muestra")
    p.add_argument("--actualizacion", action="store_true")
    p.add_argument("--prueba-actualizacion", action="store_true")
    p.add_argument("--benchmark", action="store_true")
    p.add_argument("--top", type=int, default=10)
    a = p.parse_args()

    if a.benchmark:
        return benchmark()
    if a.prueba_actualizacion:
        # El enunciado pide demostrarla con la muestra y con el conjunto completo.
        for ds in (["muestra", "full"] if a.dataset == "full" else [a.dataset]):
            prueba_actualizacion(ds)
            print()
        return

    r = ejecutar(a.dataset, a.actualizacion)
    print(f"PROCESO · {a.dataset}"
          f"{' + actualización' if a.actualizacion else ''}\n")
    _resumen(r)

    print(f"\nTOP {a.top} ACCIONABLES")
    cols = ["pedido_id", "linea_id", "cliente", "uds_pendientes",
            "puntuacion", "accion_propuesta"]
    print(r["accionables"][cols].head(a.top).to_string(index=False))

    print("\nREQUIEREN DECISIÓN (por motivo)")
    req = r["requiere_decision"]
    if req.empty:
        print("  ninguno")
    else:
        print(req["motivo"].str.replace(r"\(.*\)", "(...)", regex=True)
              .value_counts().to_string())


if __name__ == "__main__":
    main()
