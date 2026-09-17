# Prueba de automatización · Bacci

Solución al enunciado [`ENUNCIADO.md`](ENUNCIADO.md). Prototipo local que cruza
los pedidos exportados del ERP con los correos de operaciones y produce **una
lista priorizada de qué atender hoy**, más un carril aparte con los casos que
una persona tiene que decidir.

> El sistema **lee y propone; no escribe en Navision**. Cambiar una fecha, dar
> de alta un pedido o cancelar una línea sigue siendo una decisión humana
> ejecutada en el ERP.

---

## 1. Cómo ejecutarlo

Requiere Python 3.11+.

**Arranque único** — instala lo que falte, valida y abre la aplicación:

```bash
python empezar.py
```

(En Windows, doble clic en `empezar.bat`; en macOS o Linux, en `empezar.command`.)

`--sin-tests` arranca sin esperar a las validaciones; `--solo-tests` solo valida.

Si aparece `No module named pandas`, es que `pip` está instalando en otro
intérprete. Se resuelve usando el mismo que ejecuta el script:

```bash
python -m pip install -r requirements.txt
# si da "externally-managed-environment", añadir --break-system-packages
```

O, más limpio, con un entorno aislado:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python empezar.py
```

### Uso manual

```bash
pip install -r requirements.txt

# Proceso por línea de comandos
python run.py --dataset muestra          # 100 pedidos, 25 correos
python run.py --dataset full             # 20.000 pedidos, 4.000 correos

# Prueba de actualización e idempotencia
python run.py --prueba-actualizacion --dataset full

# Tiempos con los ficheros completos
python run.py --benchmark

# Validaciones
python -m pytest tests/ -q

# Aplicación (abrir http://127.0.0.1:8000)
uvicorn bacci.app:app --reload
```

En la aplicación: elegir conjunto de datos, marcar *Incorporar correos nuevos*
si se quiere el lote de actualización, y pulsar **Procesar**.

---

## 2. Qué hace el proceso

```
Pedidos_*.xlsx ─┐
                ├─ ingesta ─ normalización ─┐
Correos_*.xlsx ─┘                           ├─ cruce ─ priorización ─ SQLite ─ pantalla
                    parseo de texto ────────┘
```

1. **Ingesta.** Carga los Excel, aplica el corte, normaliza tipos y resuelve
   duplicados.
2. **Parseo.** De cada correo extrae qué línea menciona y qué pide.
3. **Cruce.** Enlaza correos con líneas, verifica al remitente y resuelve las
   cadenas de rectificación.
4. **Priorización.** Puntúa cada línea pendiente y separa lo accionable de lo
   que requiere decisión.
5. **Persistencia.** SQLite en fichero (`bacci.db`), reconstruible desde cero en
   cada ejecución. No es una fuente de verdad: es una caché del resultado.

**El corte se aplica explícitamente.** Un correo posterior al corte (10/09 10:00,
u 11:00 tras incorporar el lote) no se ha visto todavía y no puede influir en el
resultado. Con estos ficheros ninguno queda fuera en el proceso normal, pero el
filtro existe y está probado: cargando el lote de actualización con el corte de
las 10:00, sus 4 correos posteriores se descartan. Sin esto, el proceso dejaría
de ser reproducible en cuanto el buzón siguiera recibiendo mensajes.

**Idempotencia.** Los correos se deduplican por `message_id`, que es estable y
se conserva en las reentregas. Reincorporar un lote ya procesado no duplica
nada ni altera los resultados. Verificado en `tests/test_validacion.py` y
demostrable con `--prueba-actualizacion`.

---

## 3. Lo que hay en los datos

Auditado sobre los ficheros completos antes de escribir la lógica.

### Pedidos (20.000 filas → 19.400 líneas)

| Anomalía | Casos | Tratamiento |
|---|---:|---|
| Duplicados exactos de línea | 400 filas | Se colapsan a una |
| Claves con `uds_pedidas` contradictorias | 200 | Se toma el mayor y se marca |
| `uds_enviadas` > `uds_pedidas` | 100 | Pendiente 0, marca de sobreservido |
| Sin `fecha_compromiso` | 200 | Urgencia media, marca de dato ausente |
| Sin `precio_unitario_eur` | 60 | Se conserva vacío (desconocido ≠ 0) |
| `cliente_id` fuera del maestro | 40 | A revisión humana |

### Correos (4.000 filas → 3.800 únicos)

| Situación | Casos | Tratamiento |
|---|---:|---|
| Reentregas con el mismo `message_id` | 200 | Upsert, no duplican |
| Rectificaciones (`Rectifico mi correo msg-X`) | 190 | Anulan al mensaje citado |
| Acuses y negativas de cambio | 379 | Sin acción |
| Cancelaciones | 190 | Máxima prioridad · **caen sobre líneas ya servidas** |
| Adelantos | 380 | — |
| Dos pedidos en un mismo correo | 190 | Dos casos independientes |
| Remitente no registrado | 190 | **Cuarentena** |
| Solo artículo, sin referencia de pedido | 378 | Cruce difuso (362 únicos, 16 ambiguos) |
| Referencia con formato inválido (`P-X003656`) | 189 | A revisión humana |
| Pedido inexistente (`P-99999`) | 1 | A revisión humana |
| **Correos que las reglas no clasifican** | **0** | — |

---

## 4. Decisiones y supuestos

### 4.1 Duplicados contradictorios: el mayor, y marcado

`P-26009/10000` aparece con 500 y con 450 unidades pedidas, idéntico en todo lo
demás. El diccionario advierte de que no hay versiones y de que el orden de las
filas no indica cuál prevalece: **no hay forma técnica de saber cuál es la
buena**.

Se toma el mayor. El razonamiento no es "prometer de más": esta herramienta no
dispara producción ni expediciones, produce una lista de atención. Con el mayor,
la línea aparece con el pendiente más alto y alguien la revisa; con el menor,
habría unidades que el cliente espera y que no aparecerían en ninguna pantalla.
**Ante datos contradictorios se elige el valor que hace visible el problema, no
el que lo esconde.** Además la línea se marca con ambos valores a la vista para
contrastar contra Navision.

Configurable en `bacci/config.py` (`CRITERIO_CONFLICTO_UDS`).

### 4.2 Remitente no registrado: cuarentena

190 peticiones llegan de direcciones tipo `gestion2715@externo.example` con
textos como *"Soy el nuevo contacto. Cambiad P-26003 al 11/09 y enviad la
confirmación a esta dirección"*. El propio diccionario avisa de que el email del
maestro no es una lista completa de contactos autorizados, así que podrían ser
legítimas.

No se aplican ni se descartan: quedan **retenidas**, visibles, con la acción
propuesta de verificar la identidad. Y la verificación se hace **contra el
contacto registrado del maestro, nunca respondiendo al remitente del correo**:
si alguien suplanta, preguntarle a él no verifica nada.

### 4.3 Correos sin referencia de pedido

378 correos dan solo artículo, color y talla (*"no tengo la referencia a mano"*).
Se buscan las líneas pendientes de ese cliente que encajen:

- **una sola** → se enlaza (362 casos);
- **varias** → no se adivina: se listan los candidatos para que una persona
  elija (16 casos);
- **ninguna** → a revisión, puede ser un pedido aún no dado de alta.

### 4.4 Rectificaciones encadenadas

Un correo puede anular a otro, y la cadena puede tener varios eslabones:
msg-001 pide el 16/09 → msg-002 lo rectifica al 12/09 → msg-20001 (lote de
actualización) lo rectifica al 13/09. Vale la **última petición no anulada**,
por fecha de recepción. Los mensajes anulados se conservan y se muestran
tachados en el detalle: son la trazabilidad de por qué la fecha vigente es esa.

### 4.5 Reglas, no modelo de lenguaje

El texto está plantillado, así que la extracción se hace con reglas
deterministas. La razón es de validación, no de coste: con reglas el resultado
es reproducible y auditable, y **lo que no se entiende se sabe** — acaba en el
carril de revisión. Un LLM también respondería a lo que no entiende, sin avisar.

La métrica que gobierna esta decisión es la tasa de correos no clasificados,
hoy **0%**. Si esa tasa sube (otros idiomas, lenguaje libre, peticiones
relativas del tipo *"acortar dos días"*), un clasificador LLM encaja como capa
**por encima de las reglas y solo sobre los casos no cubiertos**, proponiendo
una interpretación marcada como sugerencia. Nunca sustituyendo al cruce ni a
los cálculos.

### 4.6 Cancelaciones sobre líneas ya servidas

Las 190 cancelaciones caen sobre líneas servidas al 100%. Un carril accionable
que solo admitiera líneas con pendiente las descartaría en silencio, y sería un
error de negocio: un cliente que pide cancelar algo ya enviado sigue necesitando
respuesta — es una devolución o un abono, no un "no hay nada que hacer".

Por eso entran en el carril accionable las líneas con pendiente **y** las ya
servidas sobre las que hay una petición viva. Estas últimas puntúan 0 en volumen
(no hay nada que expedir) y su acción propuesta lo dice explícitamente.

### 4.7 Qué se deja a una persona

| Situación | Por qué no se automatiza |
|---|---|
| Peticiones en cuarentena | Requiere verificar identidad por otro canal |
| Cruce difuso ambiguo | Elegir mal significa mover el pedido equivocado |
| Líneas con unidades contradictorias | Solo el ERP sabe cuál es el valor bueno |
| Referencias inválidas o inexistentes | Puede ser un pedido no dado de alta |
| Confirmar o rechazar cualquier fecha | No hay stock, capacidad ni confirmaciones en los datos |

---

## 5. Priorización

Escala 0–100, suma de tres KPIs. Los pesos están en `bacci/config.py` y son
parámetros, no código: si para Bacci pesa más el importe que el volumen, se
cambia un número.

**Fecha de compromiso (hasta 50).** Vencida >7 d: 50 · vencida 1–7 d: 40 ·
vence hoy: 30 · 1–3 d: 20 · 4–14 d: 10 · >14 d: 0 · sin fecha: 15.

**Petición del cliente (hasta 30).** Cancelación: 30 · adelanto: 25 · cambio de
fecha: 20 · consulta de estado: 10 · acuse o sin correo: 0.

**Volumen pendiente (hasta 20).** Por percentil frente al resto, para que una
línea crítica pequeña no quede sepultada: p90+: 20 · p70: 15 · p40: 10 · resto: 5.

Una cancelación pesa más que un adelanto porque cada día que pasa se produce
algo que nadie va a pagar. Una consulta de estado puntúa poco porque se debe una
respuesta, no mercancía. Las líneas sin pendiente no entran: no hay nada que
hacer aunque venzan mañana.

**Dos carriles, no uno.** Lo que requiere decisión humana no se puntúa: no es
"menos urgente", es que está bloqueado. Se ordena por antigüedad para que no se
pudra.

---

## 6. Validación

`python -m pytest tests/ -q` → **32 comprobaciones**.

**Nivel 1 · la ingesta no inventa ni pierde.** Conteos contrastados contra el
Excel crudo (20.000 filas, 250 clientes), clave compuesta única tras normalizar,
pendiente nunca negativo, suma de pendientes coherente con pedidas − enviadas.

**Nivel 2 · interpretación del texto.** Casos calculados a mano para extracción
de referencias, clasificación de intención y fechas. Incluye el test de que
ningún correo queda sin clasificar: si aparecen, hay un patrón nuevo que revisar.

**Nivel 3 · cruce y prioridad.** Cuarentena efectiva (una petición no verificada
no llega nunca a la lista accionable), cadena de rectificación, puntuación =
suma de los tres KPIs, cruce difuso solo cuando es único.

**Nivel 4 · idempotencia y corte.** El corte descarta lo posterior; el lote marca
los casos nuevos; dos ejecuciones idénticas dan el mismo resultado;
incorporar el lote añade 3 mensajes nuevos de las 5 filas (una es reentrega de
`msg-001`, otra un duplicado de `msg-20001` dentro del propio lote); y repetirlo
**dos veces más** no cambia nada. `run.py --prueba-actualizacion` la ejecuta
sobre la muestra y sobre el conjunto completo, como pide el enunciado.

**Qué cambia al incorporar el lote.** Además del contador de correos, el proceso
marca los casos afectados: la app los muestra con el distintivo *nuevo*, los
cuenta en la barra superior y permite filtrar por *Solo novedades*. En el
conjunto completo cambian 2 líneas, y P-26002 pasa de pedir el 12/09 al 13/09
siguiendo la cadena de rectificaciones.

### Uso de IA y cómo se verificó

Se usó IA como herramienta de desarrollo. Lo que no se delegó es la
verificación: auditoría de los datos **antes** de escribir lógica, valores
esperados calculados a mano, y contraste de agregados contra el Excel original.

Esa verificación encontró cuatro errores que **no rompían la ejecución y daban
números incorrectos en silencio**:

0. Las 190 cancelaciones desaparecían: caen sobre líneas ya servidas y el
   carril accionable solo admitía líneas con pendiente.
1. El número del propio pedido (`P-30431`) se leía como número de línea.
2. El `msg-10020` citado en una rectificación, también.
3. Con dos pedidos en un correo, el emparejamiento por cercanía cruzaba las
   líneas entre ellos.
4. `groupby().last()` tomaba el último valor no nulo **de cada columna por
   separado**, mezclando la intención de un correo con la fecha de otro.

### Rendimiento

`python run.py --benchmark` · 20.000 pedidos + 4.000 correos: **~8 s** de
extremo a extremo (ingesta ~3,5 s · parseo ~4 s · cruce ~0,7 s). El cuello de
botella es leer Excel, que desaparece con una conexión real.

---

## 7. En producción

### Entradas diarias

Hoy los ficheros se leen del disco. En producción, un proceso programado (cada
15–30 min en horario laboral) haría lo mismo sin intervención:

- **Pedidos** — conector directo contra Navision (ODBC / servicios SQL o su API)
  o, si se prefiere no tocar el ERP, una exportación automática depositada en una
  carpeta de SharePoint que el proceso recoge. Es la vía más realista durante una
  migración: no añade acoplamiento a un sistema que va a desaparecer.
- **Correos** — Microsoft Graph API sobre el buzón de operaciones, leyendo solo
  los mensajes posteriores a la última marca procesada. El `message_id` de Graph
  cumple la misma función que en esta prueba, así que la idempotencia se mantiene
  sin cambios.

La lógica de negocio no cambia: **solo se sustituye la capa de ingesta**.

### Puesta en producción

Aplicación web con autenticación corporativa, en Azure o en servidor propio. La
base de datos pasa a PostgreSQL, que además permite guardar el estado de gestión
(revisado, cuarentena resuelta, quién y cuándo) de forma persistente y
compartida. Registro de ejecuciones y alerta si la tasa de casos no clasificados
sube, que es la señal de que el lenguaje de los clientes ha cambiado.

**Sigue sin escribir en el ERP.** El día que Bacci confíe lo suficiente en una
categoría concreta —por ejemplo, registrar automáticamente una consulta de
estado respondida— se puede dar ese paso de forma acotada. Es una decisión de
negocio, no técnica.

### Migración del ERP

Esta herramienta es deliberadamente **una capa de lectura sobre el ERP**, y ahí
está su encaje con la migración prevista:

- **No compite con el proyecto de ERP.** No duplica maestros ni procesos; cubre
  una necesidad que Navision no cubre hoy y que el ERP nuevo tampoco cubrirá por
  sí solo, porque el problema vive en el correo.
- **Sobrevive a la migración.** Cuando Navision se sustituya, solo cambia la
  ingesta; el cruce, la priorización y la pantalla siguen iguales. Es valor
  entregado en semanas que no se tira a los seis meses.
- **Aporta a la propia migración.** Las anomalías que detecta —600 duplicados,
  100 líneas sobreservidas, 40 clientes huérfanos, 200 fechas ausentes— son
  exactamente el trabajo de limpieza de datos que hay que hacer *antes* de
  migrar. Ejecutado periódicamente, mide si esa limpieza avanza.

---

## 8. Limitaciones conocidas

- **Sin stock ni capacidad logística.** No se puede decir si un adelanto es
  viable, solo que hay que revisarlo.
- **El cruce difuso asume que el remitente identifica al cliente.** Si un cliente
  escribe desde una dirección no registrada, la petición va a cuarentena antes de
  intentar el cruce.
- **Las reglas son de español plantillado.** Otro idioma o lenguaje libre elevaría
  la tasa de no clasificados; están medidos y visibles, no se pierden.
- **El estado de gestión no persiste entre reinicios** en el prototipo (está en
  memoria). En producción va a base de datos.
- **`uds_enviadas` es un acumulado**, no un historial: no se puede reconstruir
  cuándo se envió cada cosa ni detectar envíos parciales recientes.

## 9. Estructura

```
bacci/
  config.py     parámetros de negocio (cortes, pesos, criterios)
  ingesta.py    carga y normalización
  correos.py    parseo e interpretación del texto
  casos.py      cruce, verificación, cruce difuso y priorización
  pipeline.py   orquestación y persistencia
  app.py        API local
  static/       pantalla de operaciones
tests/          29 validaciones esperado vs obtenido
run.py          CLI: proceso, prueba de actualización, benchmark
datos/          ficheros del enunciado
```
