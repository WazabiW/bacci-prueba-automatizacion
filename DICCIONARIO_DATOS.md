# Diccionario de datos

Los pedidos representan una exportación del estado del ERP al **10/09/2026 a las 10:00**, hora de Madrid (`Europe/Madrid`). Los correos iniciales llegan hasta ese corte. Las fechas y horas se interpretan en esa misma zona.

## Pedidos

Una línea se identifica por **`pedido_id` + `linea_id`**. Un pedido puede tener varias líneas.

| Campo | Significado |
| --- | --- |
| `pedido_id` | Identificador del pedido. |
| `linea_id` | Identificador de la línea dentro del pedido; trátalo como identificador, no como cantidad. |
| `cliente_id` | Referencia al maestro de clientes. |
| `sku` | Código del artículo. No se proporciona un catálogo de descripciones. |
| `color`, `talla` | Variante del artículo de la línea. |
| `uds_pedidas` | Unidades solicitadas para la línea en el ERP. |
| `uds_enviadas` | Unidades acumuladas ya expedidas al corte; no es un movimiento individual. |
| `precio_unitario_eur` | Precio por unidad en euros, sin impuestos. |
| `fecha_compromiso` | Fecha de entrega comprometida en el ERP, sin hora. Una fecha igual al día de corte vence ese día; no se considera ya vencida. |

Las filas no son un historial de cambios. Puede haber duplicados y valores contradictorios para una misma línea; no se dispone de versiones y el orden de las filas no indica cuál prevalece. Los campos vacíos representan datos desconocidos, no ceros.

## Clientes

| Campo | Significado |
| --- | --- |
| `cliente_id` | Identificador del cliente. |
| `nombre` | Nombre comercial. |
| `email` | Contacto principal registrado. Puede faltar y no constituye una lista completa de contactos autorizados. |

## Correos

La hoja `Correos` tiene la misma estructura en los tres archivos de correos.

| Campo | Significado |
| --- | --- |
| `message_id` | Identificador estable del mensaje; una reentrega conserva el mismo identificador. |
| `received_at` | Fecha y hora de recepción. |
| `from`, `to` | Direcciones del remitente y destinatario. |
| `subject`, `body` | Asunto y cuerpo del correo. Pueden mencionar una o varias líneas, rectificar mensajes o no pedir cambios. |

Una petición por correo no equivale a una modificación confirmada en el ERP. No se aportan stock, capacidad logística ni confirmaciones de recepción que permitan garantizar una nueva fecha de entrega.

## Archivo de actualización

`Correos_actualizacion.xlsx` es un lote adicional, no un reemplazo de los correos anteriores. Contiene mensajes recibidos después del corte inicial y reentregas. Para esta prueba, los pedidos se mantienen sin cambios y el corte avanza a las **11:00 del mismo día**.
