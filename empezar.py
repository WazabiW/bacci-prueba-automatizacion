#!/usr/bin/env python3
"""Arranque único.

    python empezar.py

Instala lo que falte, comprueba que el proceso funciona, levanta la aplicación
y abre el navegador. No hace falta nada más.

Opciones:
    python empezar.py --sin-tests     salta la comprobación (arranca antes)
    python empezar.py --solo-tests    solo valida, no levanta nada
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PUERTO = 8000
URL = f"http://127.0.0.1:{PUERTO}"


def paso(n: int, total: int, texto: str) -> None:
    print(f"\n[{n}/{total}] {texto}")


def dependencias() -> None:
    print(f"    Python: {sys.executable}")
    requeridos = [("pandas", "pandas"), ("openpyxl", "openpyxl"),
                  ("fastapi", "fastapi"), ("uvicorn", "uvicorn"),
                  ("pytest", "pytest")]

    def faltantes() -> list[str]:
        out = []
        for modulo, paquete in requeridos:
            try:
                __import__(modulo)
            except ImportError:
                out.append(paquete)
        return out

    faltan = faltantes()
    if not faltan:
        print("    Todo instalado.")
        return

    print(f"    Instalando: {', '.join(faltan)}")
    base = [sys.executable, "-m", "pip", "install", "-q"]
    for extra in ([], ["--break-system-packages"], ["--user"]):
        subprocess.run([*base, *extra, *faltan],
                       capture_output=True, text=True)
        # Un módulo recién instalado puede no verse sin refrescar las rutas.
        import importlib
        import site
        importlib.invalidate_caches()
        for ruta in site.getsitepackages() + [site.getusersitepackages()]:
            if ruta not in sys.path:
                sys.path.append(ruta)
        faltan = faltantes()
        if not faltan:
            print("    Listo.")
            return

    print(f"\n    No se han podido instalar: {', '.join(faltan)}")
    print("    Instálalas a mano con este mismo intérprete:\n")
    print(f"      {sys.executable} -m pip install -r requirements.txt\n")
    print("    Si da 'externally-managed-environment', añade al final:")
    print("      --break-system-packages\n")
    print("    O crea un entorno aislado:")
    print("      python -m venv .venv")
    print("      source .venv/bin/activate      (Windows: .venv\\Scripts\\activate)")
    print("      python -m pip install -r requirements.txt")
    print("      python empezar.py")
    sys.exit(1)


def comprobar() -> bool:
    print("    Procesando la muestra…")
    from bacci.pipeline import ejecutar

    r = ejecutar("muestra")
    m = r["metricas"]
    print(f"    {m['pedidos_lineas_unicas']} líneas · "
          f"{m['correos_correos_unicos']} correos · "
          f"{m['casos_accionables']} accionables · {m['t_total_s']} s")

    print("    Validaciones (tarda ~2 min, usa los ficheros completos)…")
    res = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                         cwd=RAIZ, capture_output=True, text=True)
    ultima = [l for l in res.stdout.strip().splitlines() if l.strip()][-1]
    print(f"    {ultima}")
    return res.returncode == 0


def abrir_luego() -> None:
    time.sleep(2.5)
    webbrowser.open(URL)


def main() -> None:
    solo_tests = "--solo-tests" in sys.argv
    sin_tests = "--sin-tests" in sys.argv
    total = 2 if sin_tests else 3

    print("=" * 58)
    print("  Control de pedidos · Bacci")
    print("=" * 58)

    paso(1, total, "Comprobando dependencias")
    dependencias()

    n = 2
    if not sin_tests:
        paso(n, total, "Comprobando que el proceso funciona")
        ok = comprobar()
        if not ok:
            print("\n    Alguna validación ha fallado. Revisa la salida con:")
            print("      python -m pytest tests/ -v")
            sys.exit(1)
        n += 1

    if solo_tests:
        print("\nTodo correcto.")
        return

    paso(n, total, "Levantando la aplicación")
    print(f"    {URL}")
    print("    Ctrl+C para parar.\n")
    threading.Thread(target=abrir_luego, daemon=True).start()

    import uvicorn

    try:
        uvicorn.run("bacci.app:app", host="127.0.0.1", port=PUERTO,
                    log_level="warning")
    except KeyboardInterrupt:
        print("\nParado.")


if __name__ == "__main__":
    sys.path.insert(0, str(RAIZ))
    main()
