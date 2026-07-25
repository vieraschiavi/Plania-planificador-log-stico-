# Plania · Modelo comercial

## Planes (fuente de verdad: `backend_venta/licencias.py`)

| Plan | Precio | Duración | Cupo/mes | Features |
|---|---|---|---|---|
| **Trial** | $0 | **7 días** | 300 consultas | TODO habilitado (copiloto, ERP, exportes, rutas) |
| **Starter** | USD 59 | 30 días | 500 | copiloto, erp, exportes |
| **Pro** | USD 129 | 30 días | 2.000 | + rutas, excedente |
| **Enterprise** | a medida | 30 días | sin tope | + white_label, sso, multi_sucursal |

La "consulta" (unidad de cupo) es cada llamada al gateway IA del copiloto;
el motor local de intenciones y toda la analítica son ilimitados.

## Circuito de venta (100% automático)

1. **Landing** (`landing/index.html`) → botón demo → `POST /licencias/trial`
   (una por email) → licencia JWT de 7 días full en pantalla/mail.
2. Prospecto instala el programa PC (`packaging/`) o entra a la web, pega la
   licencia (o la demo local arranca sola al primer uso).
3. Vence la demo → la app bloquea las pantallas de trabajo pero conserva
   datos y muestra **Planes & Licencia**.
4. **Pago**: `POST /checkout` crea la preferencia de MercadoPago → cliente
   paga → **webhook** verifica el pago contra la API de MP (nunca se confía
   en el body) → emite licencia definitiva + token de descarga del
   instalador → el cliente la pega en la app y sigue donde estaba.
5. Renovación: mismo circuito; el JWT lleva la expiración.

## Qué configurar para salir a producción (solo secretos/infra, el código está)

- `MP_ACCESS_TOKEN` (MercadoPago vendedor) en el servidor del backend.
- URL pública del backend en el panel de webhooks de MP y `PLANIA_WEBHOOK_URL`.
- `ANTHROPIC_API_KEY` del gateway (los clientes nunca manejan API keys).
- `PLANIA_LICENSE_SECRET` fijo (rotación de firma de licencias).
- `PLANIA_INSTALADOR_PATH` apuntando al `Plania_Setup.exe` construido con
  `python packaging/build_release.py` en Windows.
- Deploy: `Procfile` listo para Render/Railway/Fly (proceso `web` = app,
  `backend` = venta).

## Métricas a mirar (ya quedan registradas)

- `data/uso_licencias.db`: consultas por cliente/mes (facturación excedente).
- `plania/auditoria.py`: log encadenado por hash (emisiones de licencia,
  pagos, exportes) — sirve de evidencia ante disputas.
- Conversión demo→pago: emails en tabla `trials` vs licencias emitidas.
