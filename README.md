# Prueba de automatización

Del control de pedidos a la operación diaria

## El objetivo

Bacci suministra textil al *mass market*. Trabaja con un Navision antiguo, Excel y Outlook, y quiere modernizar su ERP en los próximos seis meses sin interrumpir la actividad.

Construye una **automatización y una aplicación sencilla** para que operaciones sepa **qué queda por servir, qué necesita atención y qué acción tomar**, cruzando pedidos y correos. Justifica tu priorización.

## Los archivos

| Archivo | Contenido |
| --- | --- |
| [Pedidos_full.xlsx](Pedidos_full.xlsx) | 20.000 filas de pedidos y un maestro de 250 clientes. |
| [Correos_full.xlsx](Correos_full.xlsx) | 4.000 filas de correos relacionados con la operativa. |
| [Pedidos_muestra.xlsx](Pedidos_muestra.xlsx) | 100 filas de pedidos y un maestro de 12 clientes. |
| [Correos_muestra.xlsx](Correos_muestra.xlsx) | 25 filas de correos. |
| [Correos_actualizacion.xlsx](Correos_actualizacion.xlsx) | 5 filas para probar la llegada de nuevos correos y la repetición de mensajes. |

Puedes empezar con los archivos `_muestra`, una selección de los `_full` con la misma estructura. Demuestra también el resultado completo. Consulta el [diccionario de datos](DICCIONARIO_DATOS.md).

Datos ficticios. Corte inicial: **10/09/2026 a las 10:00, hora de Madrid**. Trabaja con los archivos, sin conectar sistemas reales ni enviar correos.

## Qué construir

1. **Automatización.** Un proceso repetible que lea los archivos, cruce la información e incorpore nuevos correos sin editar filas manualmente.
2. **Aplicación mínima.** Una lista priorizada con pedido y línea, cliente, unidades pendientes, motivo y acción propuesta; filtros por cliente y prioridad; y un detalle con los datos y correos que justifican cada caso. Incluye los casos sin resolver. Basta una pantalla con su detalle, ejecutable localmente.
3. **Validación.** Comprueba cálculos, cruces y casos dudosos, mostrando resultados esperados frente a obtenidos. Demuestra la repetición del proceso y mide su tiempo con los archivos completos.

Los datos contienen anomalías. Explica tus supuestos, las limitaciones y qué decisiones dejarías a una persona.

## Prueba de actualización

1. Ejecuta el proceso con pedidos y correos iniciales.
2. Incorpora `Correos_actualizacion.xlsx` conservando los correos anteriores y los mismos pedidos. Nuevo corte: **10/09/2026 a las 11:00**.
3. Repite el paso 2. Demuestra los cambios de la primera incorporación y que repetirla no duplica mensajes ni altera los resultados.

Sirve con la muestra y el conjunto completo. Puedes recalcular todo o procesar las novedades. Esta prueba complementa tus propias validaciones.

## Qué valoraremos y qué entregar

**Priorizaremos la validación de los resultados y la utilidad para operaciones**, seguidas de la claridad de las decisiones y la facilidad de ejecución y mantenimiento.

Haz un **fork**. Conserva el enunciado y añade al README instrucciones, resultados, validaciones y una explicación breve de las entradas diarias, la conexión con Navision y Outlook y la migración del ERP.

Incluye un **vídeo** con este orden: **problema** y cómo lo has entendido; **proceso** seguido y decisiones para llegar a la solución; **demostración** de la solución y sus validaciones. Comparte las URL del fork y del vídeo con Bacci y comprueba el acceso.

El alcance es un **prototipo local**. Herramientas libres. Puedes usar IA explicando cómo verificaste su trabajo. Prioriza y documenta lo pendiente; las conexiones reales y la puesta en producción solo deben explicarse.
