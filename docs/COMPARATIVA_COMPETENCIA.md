# Plania vs. competencia (Uruguay / LATAM)

Análisis honesto para el pitch comercial: contra quién se compite de verdad
cuando un distribuidor, mayorista o comercio evalúa Plania, y qué ofrece
Plania que hoy no consigue en una sola herramienta.

## El panorama real

En Uruguay y la región, un comercio/distribuidor PyME resuelve la
planificación con alguna mezcla de:

| Alternativa | Ejemplos típicos | Qué hace bien | Dónde queda corta |
|---|---|---|---|
| **ERP local** | Zureo, Memory, GestioNet, Tango, Bejerman | Facturación, stock contable, impuestos al día | Reportes descriptivos; no dice *qué hacer*; sin IA; módulos extra caros |
| **ERP internacional** | Odoo, SAP Business One, Softland | Cobertura funcional amplia | Implementación cara y larga (consultores); sobredimensionado para PyME; sin foco UY |
| **BI genérico** | Power BI, Looker Studio, Qlik | Visualización flexible | Hay que construir todo; requiere analista; no genera acciones ni rutas; sin demo aplicada |
| **Planillas** | Excel del encargado | Costo cero, flexible | Manual, frágil, sin alertas, muere cuando se va el que la armó |
| **Ruteo puro** | SimpliRoute, Routal, Beetrack | Optimización de rutas madura | Solo logística de entrega; no toca precios, stock ni ofertas; precio por vehículo se dispara |

## Qué ofrece Plania que la combinación anterior no

1. **Decisiones, no reportes.** Cada pantalla termina en una acción con su
   porqué en pesos: *ofertá estos 12 SKUs al 15%, liberás $430.000*;
   *comprá estos 8 antes del jueves o perdés $210.000 de venta*.
2. **Conector universal con auto-mapeo.** Se conecta a la base del ERP que
   el cliente ya tiene (PostgreSQL, MySQL, SQL Server, Oracle, SQLite,
   CSV/Excel) y auto-detecta el esquema — incluidos los nombres de columna
   típicos de Zureo/Memory/Tango/Bejerman/Odoo/SAP B1. Cero migración.
3. **Copiloto IA sobre datos reales.** Chat en español rioplatense que
   calcula contra la base conectada (no inventa: cada respuesta trae la
   tabla-evidencia) y funciona incluso sin API key (motor local de
   intenciones).
4. **Informe ejecutivo exportable en 1 clic** a PDF, Word y Excel — el
   formato que el dueño y el comprador realmente circulan.
5. **Planificación comercial + logística juntas.** Ofertas, precios,
   reposición, zonas *y* rutas de reparto en el mismo producto — hoy eso
   son 2 o 3 contratos distintos.
6. **Demo 7 días full sin tarjeta** contra los datos reales del prospecto:
   el producto se vende solo mostrando plata encontrada en SU base.
7. **Comercialización regional:** precios PyME, pago con **MercadoPago**
   (la billetera que el comercio ya usa), licencia automática post-pago,
   programa PC Windows + web con los mismos datos.

## Argumentario corto (objeciones frecuentes)

- *"Ya tengo ERP"* → Perfecto: Plania no lo reemplaza, lo lee. En la demo
  de 7 días lo conectamos y te muestra plata que hoy no ves.
- *"Power BI lo hace"* → Power BI te muestra un gráfico si alguien lo
  construye y mantiene. Plania te dice qué ofertar el lunes, con descuento
  calculado y piso de margen, sin analista.
- *"Es caro"* → Starter cuesta menos que 2 horas de consultor por mes. Una
  sola oferta bien armada o un quiebre evitado paga el año.
- *"¿Y mis datos?"* → Corren en tu máquina (programa PC) o tu servidor; la
  IA solo recibe agregados calculados, nunca tu base entera; keyring del
  sistema operativo para credenciales.

## Dónde NO competir (honestidad comercial)

- Facturación electrónica / DGI: eso es del ERP, no nuestro terreno.
- Flotas grandes con telemetría en vivo: SimpliRoute/Beetrack ganan;
  nuestro ruteo apunta al distribuidor de 1–10 vehículos sin sistema.
- Corporaciones con data team: ahí el BI a medida tiene sentido; nuestro
  Enterprise entra por sucursales/white label, no por reemplazar al equipo.
