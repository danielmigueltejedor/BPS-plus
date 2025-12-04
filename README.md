# Notice

Actualmente esta integración depende de librerías científicas como **NumPy**, **SciPy** y **Shapely**.  
En hardware ARM (Raspberry Pi, etc.) puede haber problemas al compilar SciPy si el sistema no es **64 bits** o el procesador es antiguo.

- En **Raspberry Pi 5** o hardware similar (ARMv8 / 64 bits) con **Home Assistant OS de 64 bits** debería poder compilar correctamente.
- Si consigues instalarlo en otros dispositivos ARM, abre un issue en el repositorio para documentarlo mejor.

---

![BPS-plus Logo](img/icon.png)

# BLE Positioning System Plus (BPS-plus)

**BPS-plus** es un sistema de posicionamiento en interiores basado en Bluetooth Low Energy (BLE) para **Home Assistant**, que permite:

- Ver en un mapa/plano de planta la posición de tus dispositivos BLE en tiempo (casi) real.
- Saber en qué **planta** y en qué **zona/habitación** está cada dispositivo.
- Usar esa información para **automatizar** tu casa en función de la presencia y localización precisa.

Este proyecto es un fork evolucionado del trabajo original de [Hogster/BPS](https://github.com/Hogster/BPS) y se apoya inicialmente en la integración [Bermuda](https://github.com/agittins/bermuda) de [@agittins](https://github.com/agittins) para obtener distancias, pero con la intención de:

> A medio plazo ser capaz de generar sus propios sensores de distancia y funcionar **sin depender de Bermuda**, usando directamente datos de `bluetooth_proxy` (ESPHome, Shelly, etc.).

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=danielmigueltejedor&repository=BPS-plus&category=Integration)

---

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

---

## ¿Qué hace BPS-plus?

BPS-plus combina tres piezas:

1. **Distancias a dispositivos BLE**  
   Obtenidas inicialmente a través de **Bermuda** y dispositivos con `bluetooth_proxy` (ESPHome, Shelly Plus, etc.).

2. **Trilateración en 2D**  
   A partir de las distancias a varios puntos fijos (receptores BLE) calcula unas coordenadas (x, y) en el plano de tu casa.

3. **Capas de lógica domótica**  
   - Determina **en qué planta** se encuentra el dispositivo.
   - Determina **en qué zona** (zona definida por ti: salón, cocina, despacho, etc.).
   - Expone esta información a Home Assistant mediante sensores y, en el futuro, otras entidades (device_tracker, etc.).

Con esto puedes, por ejemplo:

- Encender luces al entrar en una habitación concreta llevando solo tu **Apple Watch** o móvil.
- Cambiar la **temperatura** según la planta en la que estás.
- Activar/desactivar modos de la casa en función de quién está y dónde (tú, tus padres, tus hermanas, etc.).

---

## Estado actual del proyecto

BPS-plus está en fase de desarrollo activo y trae varias mejoras sobre la integración original:

- ✅ **Configuración vía UI** (config flow / options flow):  
  - Parámetros internos sin editar archivos a mano.
  - Futuro: configuración de URL/token de HA para el panel de tracking dinámico.
- ✅ **Script JS generado dinámicamente desde Home Assistant** (planificado):  
  - El panel de BPS-plus obtiene un `script.js` servido por la propia integración.
  - No hace falta editar el JS para poner la URL o el token.
- ✅ **Compatibilidad con HACS (Custom Repository)**  
- 🔄 **Refactorización interna** para usar patrones modernos de Home Assistant:
  - `DataUpdateCoordinator` para la lógica de actualización.
  - `unique_id` estables para evitar recrear entidades.
- 🧪 **Pruebas en hardware ARM** (Raspberry Pi 5 + HAOS 64 bits).

Próximos objetivos:

- Desacoplar gradualmente la integración de **Bermuda**, de forma que BPS-plus pueda:
  - Leer directamente RSSI y timestamps de `bluetooth_proxy`.
  - Calcular distancias y trilateración sin depender de entidades externas.
- Mejorar la **precisión y estabilidad** de los cálculos.
- Añadir una **tarjeta Lovelace** específica para mostrar el mapa y los dispositivos.

---

## Requisitos

Para usar BPS-plus en su estado actual necesitas:

- **Home Assistant** funcionando.
- **HACS** instalado.
- Integración **Bermuda** configurada y funcionando, con al menos un dispositivo BLE en seguimiento.
- Al menos **tres dispositivos** que actúen como `bluetooth_proxy` (ESPHome o Shelly Plus, por ejemplo) repartidos en tu casa:
  - Con menos de tres, no se puede hacer trilateración fiable.
  - Cuantos más proxies y mejor distribuidos estén, mejor cobertura y precisión.

Recomendable:

- Varios **ESP32** repartidos por la casa (pasillos, habitaciones, salón, etc.).
- En el caso de Raspberry Pi / ARM:
  - Home Assistant OS de **64 bits**.
  - Hardware moderno (p. ej. Raspberry Pi 5).

---

## ¿Cómo funciona a alto nivel?

1. Bermuda calcula una estimación de **distancia** desde cada proxy BLE hasta tus dispositivos (móvil, reloj, etc.).
2. BPS-plus:
   - Lee las distancias disponibles para cada dispositivo.
   - Utiliza algoritmos de trilateración/aproximación con **SciPy / NumPy / Shapely**.
   - Determina unas coordenadas en el plano.
   - Proyecta esas coordenadas sobre:
     - **Plantas** definidas por ti.
     - **Zonas** rectangulares (en el futuro: formas más complejas).
3. Finalmente BPS-plus expone:
   - Sensores de **planta** por dispositivo.
   - Sensores de **zona** por dispositivo.
   - En el futuro:
     - Sensores para X/Y.
     - Entidades tipo `device_tracker` o similares.
4. Un **panel de BPS-plus** en la barra lateral de Home Assistant muestra:
   - Posición de los proxies.
   - Diseño de zonas.
   - Posición en tiempo real de los dispositivos.

---

## Instalación con HACS

1. Asegúrate de tener **HACS** instalado en tu Home Assistant.
2. En HACS, ve a **Integraciones**.
3. Abre el menú de tres puntos en la esquina superior derecha y selecciona **Custom repositories**.
4. En el campo *Repository* escribe:
