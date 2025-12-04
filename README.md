# 📍 BLE Positioning System Plus (BPS-plus) for Home Assistant

![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5?logo=home-assistant)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-experimental-orange.svg)
![GitHub](https://img.shields.io/badge/hosted%20on-GitHub-black?logo=github)

Integración **no oficial** para crear un sistema de **posicionamiento interior BLE** en **Home Assistant**.  
Permite localizar dispositivos Bluetooth en el **plano de tu casa**, determinar **en qué planta** y **en qué zona** están, y usar esa información en automatizaciones inteligentes.

> ⚠️ **Aviso sobre ARM / SciPy**  
> Esta integración usa **NumPy / SciPy / Shapely**, que requieren compilación en ARM.  
> En una **Raspberry Pi 5 con HAOS 64 bits** funciona correctamente.  
> En ARM de 32 bits o hardware antiguo puede fallar la instalación.

> 🟡 Proyecto no afiliado a Home Assistant, ni a los autores originales de BPS/Bermuda.  
> Uso personal y educativo.

---

## ✨ Características

- Posicionamiento BLE mediante **trilateración** usando datos de `bluetooth_proxy`.
- Distancias obtenidas inicialmente desde **Bermuda**.
- Cálculo de:
  - **Planta** del dispositivo.
  - **Zona/habitación**.
  - (Planificado) **Coordenadas X/Y** y calidad de señal.
- Panel lateral para:
  - Colocar receptores.
  - Dibujar zonas.
  - Ver movimiento en tiempo real.
- Arquitectura moderna:
  - `config_flow`
  - `DataUpdateCoordinator`
  - Entidades estables con `unique_id`
- **Objetivo futuro:** independencia total de Bermuda calculando distancias internamente a partir de RSSI.

---

## 🧩 Instalación

### 🔹 Opción 1 — HACS (Recomendada)

1. Abre **HACS → Integrations**  
2. Menú → **Custom repositories**
3. Añade: `danielmigueltejedor/BPS-plus`
4. Category → `Integration`
5. Instala **BPS-plus**
6. Reinicia Home Assistant

---

### 🔹 Opción 2 — Instalación manual

1. Descarga el repo:  
   https://github.com/danielmigueltejedor/BPS-plus
2. Copia los archivos en:

```
config/custom_components/bps
```

3. Reinicia Home Assistant

---

### 🔹 Opción 3 — Terminal SSH

```
mkdir -p /config/custom_components
rm -rf /config/custom_components/bps

cd /config
git clone --depth=1 https://github.com/danielmigueltejedor/BPS-plus.git .bps-plus-tmp
cp -r .bps-plus-tmp/custom_components/bps /config/custom_components/

rm -rf /config/.bps-plus-tmp
```

Reinicia Home Assistant.

---

## 🔄 Actualización

```
rm -rf /config/custom_components/bps
cd /config
git clone --depth=1 https://github.com/danielmigueltejedor/BPS-plus.git .bps-plus-tmp
cp -r .bps-plus-tmp/custom_components/bps /config/custom_components/
rm -rf /config/.bps-plus-tmp
```

Reinicia Home Assistant.

---

## ⚙️ Configuración

1. **Ajustes → Dispositivos y servicios → Añadir integración**
2. Buscar: **BPS-plus**
3. Seleccionar dispositivos BLE detectados por Bermuda
4. Ajustar parámetros internos
5. Guardar
6. Aparecerán entidades + panel lateral

---

## 📊 Entidades creadas

| Entidad | Descripción |
|--------|-------------|
| `sensor.bps_<device>_floor` | Planta detectada |
| `sensor.bps_<device>_zone` | Zona/habitación |
| `sensor.bps_<device>_x` *(planificado)* | Coordenada X |
| `sensor.bps_<device>_y` *(planificado)* | Coordenada Y |
| `sensor.bps_<device>_distance_error` | Error del cálculo |
| `sensor.bps_<device>_last_update` | Última actualización |

---

## 🎯 Automatizaciones de ejemplo

### Encender luz al entrar en la cocina

```yaml
trigger:
  - platform: state
    entity_id: sensor.bps_apple_watch_daniel_zone
    to: "Cocina"
action:
  - service: light.turn_on
    target:
      entity_id: light.cocina
```

### Luz suave si alguien sube a planta 1 por la noche

```yaml
trigger:
  - platform: state
    entity_id: sensor.bps_padre_floor
    to: "1"
condition:
  - condition: sun
    after: sunset
action:
  - service: light.turn_on
    data:
      brightness: 20
    target:
      entity_id: light.pasillo_1
```

---

## 🧠 Detalles técnicos

- **Distancias:** proporcionadas por Bermuda  
- **Cálculo:** trilateración con SciPy, ajuste y minimización de error  
- **Zonas:** detección por geometría (Shapely)  
- **Coordenadas:** sistema interno normalizado  
- **Roadmap:**
  - Sustituir Bermuda por cálculo propio desde RSSI
  - Soporte para zonas poligonales
  - Tarjeta Lovelace de seguimiento
  - Exportar datos históricos de movimiento

---

## 🧑‍💻 Autor

- **[@danielmigueltejedor](https://github.com/danielmigueltejedor)**  
- Repositorio: https://github.com/danielmigueltejedor/BPS-plus  
- Licencia: MIT  
- Versión: 0.1.0

---

## ⚠️ Créditos y legal

Basado en:

- **Hogster/BPS**
- **agittins/Bermuda**

Proyecto no afiliado a Home Assistant.

La precisión depende de la posición de los bluetooth_proxy, interferencias y estructura de la vivienda.
