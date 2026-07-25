# Plania · Análisis de negocio, rentabilidad y posibilidad de éxito

Todos los números de este documento salen de `plania/negocio.py` y se pueden
recalcular en cualquier momento:

```bash
python3 -c "from plania import negocio; print(negocio.comparativa_escenarios())"
```

o interactivamente en el panel del dueño (`app/owner.py` → *Proyección de
rentabilidad*), moviendo escenario, inversión en redes y horizonte.

**Importes en USD. Tipo de cambio de trabajo: 40 UYU/USD.**

---

## 1. La conclusión primero

| | |
|---|---|
| **¿Es un negocio viable?** | Sí, en el escenario base y optimista. **No en el conservador.** |
| **¿Reemplaza un sueldo?** | Base con pauta: **mes 9**. Optimista con pauta: mes 3. Conservador: **nunca** en 18 meses. |
| **¿Cuánta plata hay que tener?** | Entre USD 1.240 (base) y USD 3.292 (conservador) de colchón para el pozo de caja. |
| **¿Escala a una empresa con empleados?** | Solo en el escenario optimista, y recién al mes 18 con la primera contratación. |
| **¿Alcanza con Uruguay?** | Para vivir bien uno solo, sí. Para armar una empresa de 10 personas, no. |

**Lo más importante que dice el modelo:** el cuello de botella no es la
demanda, es **la capacidad de implementar**. Cada cliente consume entre 12 y
20 horas de puesta en marcha contra su ERP. Un especialista solo, con 160
horas al mes y descontando venta y soporte, no pasa de ~7 implementaciones
mensuales por más leads que entren.

---

## 2. Los tres escenarios

No son "malo / medio / bueno" arbitrarios. Se diferencian en las variables
que de verdad mueven la aguja:

| Variable | Conservador | Base | Optimista |
|---|---|---|---|
| Leads orgánicos / mes | 6 | 10 | 16 |
| Conversión lead → demo | 30% | 40% | 50% |
| Conversión demo → cliente | 10% | 16% | 24% |
| Ciclo de venta | 3 meses | 2 meses | 1 mes |
| Churn mensual | 4,5% | 3,0% | 2,0% |
| Precio de implementación | USD 450 | USD 700 | USD 950 |
| Horas por implementación | 20 | 15 | 12 |
| ARPU (mix de planes) | USD 98 | USD 123 | USD 163 |

---

## 3. Rentabilidad neta a 1, 3, 6, 12 y 18 meses

### Resultado neto acumulado (USD)

| Escenario | Redes | 1 mes | 3 meses | 6 meses | 12 meses | 18 meses |
|---|---|---|---|---|---|---|
| Conservador | sin | −320 | −960 | −1.726 | −2.730 | **−3.292** |
| Conservador | USD 300/mes | −620 | −1.860 | −2.944 | −3.000 | **−1.289** |
| Base | sin | −320 | −776 | −283 | 2.895 | **8.345** |
| Base | USD 300/mes | −620 | −1.179 | 2.335 | 17.479 | **35.435** |
| Optimista | sin | −320 | 1.215 | 7.591 | 27.459 | **53.159** |
| Optimista | USD 300/mes | −620 | 5.615 | 26.755 | 78.941 | **155.130** |

### Clientes activos y MRR al mes 18

| Escenario | Redes | Clientes | MRR | Empleados |
|---|---|---|---|---|
| Conservador | sin | 1,9 | USD 187 | 0 |
| Conservador | USD 300/mes | 7,6 | USD 749 | 0 |
| Base | sin | 8,1 | USD 995 | 0 |
| Base | USD 300/mes | 29,9 | USD 3.680 | 0 |
| Optimista | sin | 30,5 | USD 4.957 | 0 |
| Optimista | USD 300/mes | 104,7 | USD 17.041 | 1 |

### Hitos que importan

| Escenario | Redes | Equilibrio | Supera un sueldo | Caja mínima | LTV/CAC | Payback |
|---|---|---|---|---|---|---|
| Conservador | sin | nunca | nunca | −3.292 | **0,26** | 97 meses |
| Conservador | USD 300 | mes 10 | nunca | −3.223 | **0,84** | 30 meses |
| Base | sin | mes 4 | nunca | −776 | 2,09 | 18 meses |
| Base | USD 300 | mes 3 | **mes 9** | −1.240 | **6,10** | 6 meses |
| Optimista | sin | mes 2 | mes 6 | −320 | 16,01 | 3,4 meses |
| Optimista | USD 300 | mes 2 | mes 3 | −620 | 42,34 | 1,3 meses |

> "Supera un sueldo" = el negocio le deja al fundador más de **USD 2.200 al
> mes** de forma sostenida, que es lo que este mismo perfil gana empleado en
> Uruguay. Es la vara honesta: un negocio que da ganancia pero menos que un
> sueldo todavía no es una decisión racional.

---

## 4. ¿Conviene invertir en redes?

**Sí en base y optimista. No arregla el escenario conservador.**

| Escenario | Sin redes (18m) | Con USD 300/mes | Diferencia | Inversión total |
|---|---|---|---|---|
| Conservador | −3.292 | −1.289 | +2.003 | 5.400 |
| Base | 8.345 | 35.435 | **+27.090** | 5.400 |
| Optimista | 53.159 | 155.130 | **+101.971** | 5.400 |

En el escenario base, cada dólar puesto en pauta devuelve **USD 5**. En el
optimista, USD 19. Pero en el conservador la pauta recupera USD 2.003 sobre
USD 5.400 invertidos: **pierde plata**.

La regla práctica: **el LTV/CAC decide si se pauta.** Por debajo de 3, cada
peso de pauta compra clientes que no llegan a devolver lo que costaron. En
el escenario conservador el LTV/CAC es 0,84 — pautar ahí es acelerar la
pérdida. Lo que hay que arreglar primero no es el presupuesto: es la
conversión y el churn.

**Orden correcto:** conseguir los primeros 5 clientes a pie (sin pauta),
medir la conversión real y el churn real, y **recién entonces** decidir si
pautar. Los tres escenarios existen justamente porque hasta el quinto
cliente nadie sabe en cuál está.

---

## 5. Dónde poner el esfuerzo (sensibilidad)

Del modelo, a 12 meses, escenario base con pauta:

| Si el churn mensual es… | Clientes mes 12 | Neto acumulado |
|---|---|---|
| 1,5% | 20,4 | 17.822 |
| 3,0% (base) | 19,2 | 17.479 |
| 6,0% | 17,1 | 16.838 |

| Si la conversión demo → cliente es… | Clientes mes 12 | Neto acumulado |
|---|---|---|
| 8% | 9,5 | 4.948 |
| 16% (base) | 19,2 | 17.479 |
| 28% | 34,0 | 32.468 |

**La conversión pesa muchísimo más que el churn, y no está cerca.**
Cuadruplicar el churn (de 1,5% a 6%) empeora el resultado apenas un **5,5%**.
Pasar la conversión de 8% a 28% lo multiplica por **6,6**.

La razón es estructural y conviene entenderla: en los primeros 18 meses la
base de clientes es tan chica que el churn casi no tiene sobre qué actuar
—perder el 6% de 19 clientes es perder uno—, mientras que la conversión
multiplica la entrada mes a mes y ese efecto se compone.

Traducción práctica: invertir en **cerrar mejor las demos** (acompañar la
prueba de 7 días, hacer la implementación en vivo, mostrar el número de
capital inmovilizado en la primera reunión) rinde más que cualquier otra
optimización. El churn recién pasa a ser prioridad cuando hay 50+ clientes.

Y ahí está la ventaja del producto: la demo de 7 días **ya muestra plata
concreta** del negocio del prospecto. Esa es la palanca de conversión.

---

## 6. Mercado potencial: Uruguay, LATAM y el mundo

Base: INE/ANDE — **148.500 microempresas, 21.000 pequeñas, ~5.000 medianas y
850 grandes** (≈175.350 activas); el comercio es el **33,3%** del padrón.

| Mercado | TAM (empresas) | TAM anual | SAM (empresas) | SAM anual | SOM 18m | SOM 18m anual |
|---|---|---|---|---|---|---|
| **Uruguay** | 8.700 | USD 14,4 M | 3.200 | USD 5,3 M | 45 | USD 74.250 |
| **LATAM** | 850.000 | USD 1.232 M | 190.000 | USD 275 M | 120 | USD 174.000 |
| **Mundo** | 9.500.000 | USD 22.800 M | 1.400.000 | USD 3.360 M | 25 | USD 60.000 |

**El TAM uruguayo son las pequeñas (5-19 empleados) y medianas del sector
comercio.** Las microempresas de hasta 4 personas quedan afuera a propósito:
no pagan USD 59/mes por un software adicional, y meterlas en el cálculo
solo sirve para inflar una presentación.

### Lectura de cada mercado

**Uruguay — el mercado para empezar, no para escalar.**
A favor: se llega a pie. Una reunión presencial en Montevideo cierra ventas
que en otro país exigen tres meses de pauta. El boca a boca entre
distribuidores del mismo rubro funciona.
En contra: con SOM de 45 empresas en 18 meses, el techo de un equipo chico
llega rápido. Uruguay financia el arranque; no sostiene una empresa de 10
personas.

**LATAM — el mercado para escalar, con una condición.**
Argentina, Chile, Paraguay y Perú comparten idioma, ERPs parecidos y
MercadoPago. El límite no es la demanda: es que **la implementación asistida
no viaja**. Cruzar a LATAM exige productizar el onboarding (que el cliente
conecte su ERP solo, con el auto-mapeo que ya está construido) o conseguir
partners locales que implementen a cambio de una comisión.

**Mundo — no en este plan.**
Solo tiene sentido en modo self-service puro y en inglés. Es una apuesta de
año 2 o 3. Ponerlo en el plan de 18 meses es fantasía.

---

## 7. Competencia y posibilidad real de éxito

### Contra quién se compite de verdad

| | Qué hacen | Precio típico | Dónde Plania gana | Dónde pierde |
|---|---|---|---|---|
| **ERP locales** (Zureo, Siigo Memory, Tango) | Facturación, stock contable, DGI | UYU 1.500–5.000/mes | No dicen *qué hacer*: son descriptivos | Ya están instalados y son el "sistema oficial" |
| **BI genérico** (Power BI, Looker) | Visualización a medida | USD 10–20/usuario + consultor | No requiere analista ni construir nada | Marca conocida, flexibilidad total |
| **Ruteo puro** (SimpliRoute, Routal) | Optimización de entregas | USD 20–40/vehículo | Cubre comercial + logística junto | Ruteo mucho más maduro |
| **Excel del encargado** | Todo, mal | USD 0 | Automático, no depende de una persona | Gratis y ya funciona "bastante bien" |

### El obstáculo comercial número uno (dato de la investigación)

Los ERP uruguayos cobran **UYU 1.500–5.000/mes**. Plania Starter (USD 59 ≈
UYU 2.360) y Pro (USD 129 ≈ UYU 5.160) son un **gasto adicional**, no un
reemplazo: para el cliente significa entre duplicar y triplicar su factura
de software.

Esto define toda la estrategia comercial:

1. **Nunca vender por funcionalidades** — compiten contra un ERP que ya
   tiene más funciones. Vender por **retorno**: "tenés USD X inmovilizados".
2. **Entrar por Starter, no por Pro.** USD 59 es una decisión que el dueño
   toma solo; USD 129 ya pasa por una reunión.
3. **Cobrar la implementación aparte** (USD 450–950) y que se pague sola con
   el primer hallazgo de la demo. Es el ingreso que sostiene los primeros
   meses, cuando el MRR todavía es chico.
4. La demo de 7 días **con datos reales del prospecto** es el argumento
   entero: si en esa semana el sistema no encuentra plata, no hay venta — y
   está bien que no la haya.

### Probabilidad de éxito, por objetivo

| Objetivo | Probabilidad | Por qué |
|---|---|---|
| Un negocio unipersonal rentable en Uruguay | **Alta** | Costos fijos bajísimos (USD ~230/mes). Con 5-8 clientes ya supera el punto de equilibrio. |
| Reemplazar un sueldo de USD 2.200 en 12 meses | **Media** | Solo en base con pauta (mes 9) u optimista. En conservador no pasa. |
| Empresa con 2-3 empleados a 18 meses | **Media-baja** | Requiere el escenario optimista *y* empezar a cruzar a LATAM. |
| Producto self-service que escale sin implementación | **Baja a 18 meses** | El auto-mapeo ya existe, pero una PyME sin acompañamiento no conecta su ERP sola. Es el trabajo de producto del año 2. |

---

## 8. El plan de escalado: de vender solo a tener equipo

El modelo contrata cuando se cumplen **dos** condiciones a la vez (no una):
las horas necesarias superan la capacidad, **y** el mes deja resultado
suficiente para pagar el sueldo con 30% de colchón. Contratar solo porque
falta tiempo, sin caja, es la forma más común de fundir un negocio de
servicios.

**Costo real de contratar en Uruguay:** un implementador semi-senior gana
UYU 71.000–105.000 nominales; con cargas sociales el costo empresa es
**≈1,55×** el nominal → unos USD 3.000/mes.

| Etapa | Clientes | Quién | Foco |
|---|---|---|---|
| **1. Fundador solo** (meses 1-9) | 0-15 | Vos | Implementar, aprender qué ERPs aparecen, documentar cada conexión |
| **2. Primer implementador** (meses 10-18) | 15-40 | +1 técnico | Vos vendés, él implementa. Es el cuello de botella que se libera primero |
| **3. Comercial** (mes 18+) | 40-80 | +1 comercial | Recién acá el fundador sale de la venta diaria |
| **4. Soporte / éxito del cliente** | 80+ | +1 | El churn se ataca con contacto proactivo, no con features |

**Cuándo NO contratar:** si el backlog de implementaciones se resuelve
mejorando el proceso (plantillas de mapeo por ERP conocido, guion de
capacitación grabado), bajar de 15 a 10 horas por implementación equivale a
contratar medio empleado, gratis y sin riesgo.

---

## 9. Riesgos reales

| Riesgo | Impacto | Qué lo mitiga |
|---|---|---|
| Es un gasto **adicional** al ERP | Alto — es la objeción número uno | Vender por retorno; entrar por Starter |
| El ciclo de venta se estira a 4+ meses | Alto — mata la caja | Cobrar la implementación por adelantado |
| Un ERP local copia la funcionalidad | Medio — tienen la base instalada | Velocidad y el copiloto sobre datos reales |
| Dependencia de una sola persona | Alto | Documentar cada implementación desde el cliente 1 |
| Churn alto por falta de uso | Medio | El panel del dueño ya marca clientes sin actividad hace 14 días |
| Tope de Monotributo (UYU 1.175.537/año) | Medio | El modelo ya simula el salto a IRAE; avisar al contador antes |

---

## 10. Qué haría con esto (recomendación)

1. **No pautar todavía.** Conseguir los primeros 5 clientes a pie, cobrando
   implementación. Ahí se descubre en qué escenario estás realmente.
2. **Medir dos números y solo dos:** conversión demo → cliente, y churn a los
   3 meses. Cargarlos en `plania/negocio.py` y volver a correr el modelo con
   datos propios en vez de supuestos.
3. **Si el LTV/CAC pasa de 3**, recién ahí poner los USD 300/mes de pauta.
4. **Documentar cada implementación** desde la primera: cada ERP que
   aparezca es una plantilla de mapeo que hace la siguiente más rápida. Bajar
   las horas de implementación es la palanca más barata que existe.
5. **Cruzar a LATAM** solo cuando el onboarding funcione sin vos en la sala.

---

## Fuentes consultadas (julio 2026)

- INE / ANDE — Demografía de empresas y monitor de MPYMES (cantidad de
  empresas por tamaño y participación del comercio).
- BPS / DGI — Régimen de Monotributo: tope de facturación anual para
  unipersonales (UYU 1.175.537) y composición de la cuota.
- Mercado Pago Uruguay — Comisiones por cobro (1,8%–4,99% + IVA según medio
  de pago y plazo de acreditación).
- Glassdoor / Computrabajo / Talently — Rangos salariales de perfiles
  técnicos en Uruguay (semi-senior: UYU 71.000–105.000 nominales).
- Siigo Memory y Zureo — Posicionamiento y rangos de precio de software de
  gestión para PyME en Uruguay.

Los parámetros tributarios y de costo laboral están marcados con
`[VERIFICAR]` en `plania/negocio.py`: **confirmalos con un contador antes de
tomar decisiones de plata.** Este modelo dimensiona un negocio; no reemplaza
asesoramiento contable.
