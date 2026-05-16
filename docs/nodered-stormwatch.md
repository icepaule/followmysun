---
title: NodeRED Sturmwarnung-Flow
---

# Sturmwarnung-Automatik mit Home Assistant + NodeRED

**Status: live deployed und verifiziert (Stand 16.05.2026)**

Ziel: Bei aktiver Unwetterwarnung wird das PV-Panel automatisch in die sichere Position (flach auf dem Dach, `MIN_ANGLE = 32°`) gefahren – ohne dass jemand zuhause sein muss. Bei Entwarnung kehrt das System in den Auto-Modus zurück.

## Architektur

```
[DWD Warnstufe]   [NINA Schwere]   [Manual-Override]
       │                │                  │
       └────────────────┴──────────────────┘
                        │
                        ↓
       [HA Aggregat-Sensor:
        binary_sensor.pv_emergency_trigger]
                        │   (state-change)
                        ↓
       [NodeRED Flow "Solar PV-Emergency"]
              │           ↑
              │           │ (Echo-Monitor)
              ↓           │
        [MQTT cmnd/solar/EMERGENCY]
              │           │
              │           │
              ↓           │
        [ESP12F]──────────┘
        Panel auf MIN_ANGLE       (Echo: tele/solar/SENSOR/Emergency)
```

## Komponente 1: HA-Aggregat-Sensor

`binary_sensor.pv_emergency_trigger` wird `true` wenn **mindestens eine** der drei Bedingungen zutrifft:

| Bedingung | Quelle |
|---|---|
| `DWD current_warning_level >= 2` für Ottobrunn | DWD Weather Warnings Integration |
| NINA-Schwere = "Schwer" oder "Extrem" | NINA-Integration |
| `input_boolean.pv_emergency_force = on` | Manueller Override-Switch im HA |

Der Sensor hat zusätzlich ein Attribut `reason`, das im Klartext zeigt, warum er getriggert hat – z.B. `"DWD Level 3 + NINA Schwer"`. Praktisch fürs Dashboard und für die Notification.

### Beispiel: template binary_sensor

```yaml
template:
  - binary_sensor:
      - name: "PV Emergency Trigger"
        unique_id: pv_emergency_trigger
        state: >
          {{ states('sensor.dwd_current_warning_level_ottobrunn') | int(0) >= 2
             or states('sensor.nina_warning_severity') in ['Schwer','Extrem']
             or is_state('input_boolean.pv_emergency_force','on') }}
        attributes:
          reason: >
            {% set parts = [] %}
            {% set lvl = states('sensor.dwd_current_warning_level_ottobrunn') | int(0) %}
            {% if lvl >= 2 %}{% set parts = parts + ['DWD Level ' ~ lvl] %}{% endif %}
            {% set sev = states('sensor.nina_warning_severity') %}
            {% if sev in ['Schwer','Extrem'] %}{% set parts = parts + ['NINA ' ~ sev] %}{% endif %}
            {% if is_state('input_boolean.pv_emergency_force','on') %}{% set parts = parts + ['Manual-Override'] %}{% endif %}
            {{ parts | join(' + ') if parts else 'kein Trigger' }}
```

## Komponente 2: NodeRED-Flow „Solar PV-Emergency"

Eigener Tab mit drei Gruppen:

### Gruppe „Trigger"
- **Node `server-state-changed`** – lauscht auf `binary_sensor.pv_emergency_trigger`
- **Switch-Node** – verzweigt: state == `on` → Pfad ON, state == `off` → Pfad OFF

### Gruppe „Publish"
- **Function-Node ON** baut MQTT-Payload:
  ```javascript
  return {
      topic:   'cmnd/solar/EMERGENCY',
      payload: 'on',
      retain:  true,
      qos:     1
  };
  ```
- **Function-Node OFF** analog mit `payload: 'off'`
- **MQTT-out** über Broker-Konfiguration `mqtt_nuc`

### Gruppe „Echo-Monitor"
- **Server-state-changed** auf `binary_sensor.solartracker_emergency_echo`
- Loggt / visualisiert die Quittung des ESP zurück nach HA (ca. 2 s Reaktionszeit)

### Bonus: Startup-Inject
- **Inject-Node** auf `flow start` mit `delay: 10s`
- Republisht den aktuellen `pv_emergency_trigger`-State, damit der Zustand auch nach NodeRED-Restarts neu rausgeht (sonst würde der Broker den retained-State weiter halten, was OK ist – aber so ist NodeRED auch konsistent)

## Komponente 3: HA-Echo-Sensor

```yaml
mqtt:
  binary_sensor:
    - name: "Solartracker Emergency Echo"
      unique_id: solartracker_emergency_echo
      state_topic: "tele/solar/SENSOR/Emergency"
      payload_on: "true"
      payload_off: "false"
      device_class: safety
      icon: mdi:shield-home
```

Das ist die **Quittung vom ESP**: erst wenn der Echo-Sensor auf `on` umspringt, hat der Aktuator wirklich die Anweisung empfangen. Latenz im Live-Test: ~2 s.

## Komponente 4: Dashboard-Card

Eine Subview im HA-Dashboard zeigt:

- **Trigger** (`binary_sensor.pv_emergency_trigger`)
- **Grund** (Attribute `reason`)
- **Echo** vom ESP (`binary_sensor.solartracker_emergency_echo`)
- **Force-Switch** (`input_boolean.pv_emergency_force`)
- **DWD-Level** (`sensor.dwd_current_warning_level_ottobrunn`)
- **NINA-Status** (`sensor.nina_warning_severity`)

So sieht man auf einen Blick: ist es scharf, warum, und hat der ESP es quittiert.

## Live-Test (Stand 16.05.2026, 19:59)

| Schritt | Ergebnis |
|---|---|
| `input_boolean.pv_emergency_force` → on | `pv_emergency_trigger` springt auf on |
| NodeRED publisht `cmnd/solar/EMERGENCY = on retain` | gesendet |
| ESP empfängt → `stat/solar/DEBUG` *"Emergency ON"* | empfangen |
| ESP publisht `tele/solar/SENSOR/Emergency = true` | empfangen |
| HA-Echo (`solartracker_emergency_echo`) flippt auf on | **~2 s nach Trigger** |
| `pv_emergency_force` → off | umgekehrte Sequenz, sauber |

## Persistenz nach ESP-Reboot

Weil das MQTT-Command mit `retain=true` gesendet wird, hält der Broker es. Wenn das ESP rebootet (Stromausfall, WDT-Reset, Update), subscribed es beim Boot wieder auf `cmnd/solar/EMERGENCY` – und der Broker liefert sofort den retained Wert nach. Falls dieser `on` ist, ist das ESP **unmittelbar nach dem Boot wieder im Notfallmodus**, ohne dass NodeRED etwas tun muss.

## Backups

Vor dem Deployment wurden gesichert:
- `flows.json.bak.pre-pv-emergency-20260516-195501`
- `energie_v2.yaml.bak.pre-solartracker-20260516-192320`

## Optional: Notifications

```yaml
automation:
  - alias: "PV-Notfall-Aktivierung melden"
    trigger:
      - platform: state
        entity_id: binary_sensor.solartracker_emergency_echo
        to: 'on'
    action:
      - service: notify.mobile_app
        data:
          title: "Solar-Panel im Notfallmodus"
          message: >
            Panel auf 32° flach. Grund:
            {{ state_attr('binary_sensor.pv_emergency_trigger','reason') }}
```

Damit weißt du sofort wenn DWD/NINA das System scharfgeschaltet hat und du nicht zufällig im Garten warst.
