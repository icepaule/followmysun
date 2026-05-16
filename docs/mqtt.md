---
title: MQTT-Integration
---

# MQTT-Topics

Alle Topics, ihre Bedeutung und Beispiele für Home-Assistant + Node-RED.

## Telemetrie (ESP → Broker)

Wird alle 30 s gesendet, zusätzlich sofort bei Motor-Statuswechsel.

### Vollpayload (JSON)

**Topic:** `tele/solar/SENSOR`

```json
{
  "Time": "16.05.2026 18:35:18",
  "SENSOR": {
    "PanelAngle": 35.4,
    "PanelAngleRaw": 122.7,
    "TargetAngle": 42.1,
    "SunAngle": 45.0,
    "MinAngle": 32.0,
    "MaxAngle": 58.7,
    "SensorOffset": 87.3,
    "SensorSign": 1,
    "Tolerance": 2.0,
    "Motion": 1,
    "MotionText": "Hoch",
    "Manual": false,
    "Emergency": false,
    "IsNight": false
  },
  "SYSTEM": {
    "Uptime": 3612,
    "HeapFree": 14400,
    "WiFiRSSI": -70,
    "NTPSyncCount": 1,
    "BootTime": "16.05.2026 17:35:06",
    "LastError": null
  },
  "STATUS": {
    "Online": true,
    "IP": "192.168.178.92"
  }
}
```

### Einzel-Topics (für HA-Sensoren)

| Topic | Beispiel | Typ | Beschreibung |
|---|---|---|---|
| `tele/solar/SENSOR/PanelAngle` | `35.4` | float | Aktueller Winkel zur Horizontalen (kalibriert) |
| `tele/solar/SENSOR/PanelAngleRaw` | `122.7` | float | Roh-MPU-Wert (Debug/Kalibrierung) |
| `tele/solar/SENSOR/TargetAngle` | `42.1` | float | Soll-Winkel |
| `tele/solar/SENSOR/SunAngle` | `45.0` | float | Berechneter optimaler Winkel (vor Clamping) |
| `tele/solar/SENSOR/MinAngle` | `32.0` | float | Mechanisches Untermass |
| `tele/solar/SENSOR/MaxAngle` | `58.7` | float | Mechanisches Obermass |
| `tele/solar/SENSOR/Motion` | `1` | int | 0 = Stopp, 1 = Hoch, 2 = Runter |
| `tele/solar/SENSOR/MotionText` | `Hoch` | string | Lesbar |
| `tele/solar/SENSOR/Manual` | `false` | bool | True wenn Manual-Override aktiv |
| `tele/solar/SENSOR/Emergency` | `false` | bool | True im Notfallmodus |
| `tele/solar/SENSOR/IsNight` | `true` | bool | True nach Sonnenuntergang |

### Status-Topics

| Topic | Bedeutung |
|---|---|
| `stat/esp_solar/STATUS` | `online` / `offline` (retained, last-will) |
| `stat/solar/DEBUG` | JSON mit Motor-Events und Fehlern |

## Commands (Broker → ESP)

### Notfall-Modus

**Topic:** `cmnd/solar/EMERGENCY`
**Payload:** `on`, `off`, `1`, `0`, `true`, `false`, `yes`

```bash
mosquitto_pub -h <broker> -u user -P pw \
  -t cmnd/solar/EMERGENCY -m on -r
```

Das `-r` (retain) ist **wichtig** – sonst geht der Notfall-Zustand beim nächsten ESP-Reboot verloren.

Bei `EMERGENCY=on`:
- `target = MIN_ANGLE` (z.B. 32°)
- Manual-Override wird gelöscht
- Astro-Berechnung und IsNight werden ignoriert
- Echo zurück auf `tele/solar/SENSOR/Emergency = true`
- Webseite zeigt roten NOTFALL-Banner

## Home Assistant Konfiguration

In `configuration.yaml`:

```yaml
mqtt:
  sensor:
    - name: "Solar Panel-Winkel"
      state_topic: "tele/solar/SENSOR/PanelAngle"
      unit_of_measurement: "°"
      icon: "mdi:angle-acute"
    - name: "Solar Ziel-Winkel"
      state_topic: "tele/solar/SENSOR/TargetAngle"
      unit_of_measurement: "°"
    - name: "Solar Motor-Status"
      state_topic: "tele/solar/SENSOR/MotionText"
      icon: "mdi:cog"

  binary_sensor:
    - name: "Solar Notfall"
      state_topic: "tele/solar/SENSOR/Emergency"
      payload_on: "true"
      payload_off: "false"
      device_class: safety

  switch:
    - name: "Solar Notfall-Modus"
      command_topic: "cmnd/solar/EMERGENCY"
      state_topic: "tele/solar/SENSOR/Emergency"
      payload_on: "on"
      payload_off: "off"
      state_on: "true"
      state_off: "false"
      retain: true
```

## Node-RED bei Unwetterwarnung

```javascript
// Beispiel-Flow: bei aktiver Unwetterwarnung Panel sichern
if (msg.payload === true || msg.payload === "active") {
    return {
        topic: "cmnd/solar/EMERGENCY",
        payload: "on",
        retain: true
    };
} else {
    return {
        topic: "cmnd/solar/EMERGENCY",
        payload: "off",
        retain: true
    };
}
```

## Topic-Übersicht zum Subscribe

```bash
# Alles anschauen
mosquitto_sub -h <broker> -u user -P pw -t 'tele/solar/#' -t 'stat/solar/#' -v

# Nur State-Werte
mosquitto_sub -h <broker> -u user -P pw -t 'tele/solar/SENSOR/+' -v
```
