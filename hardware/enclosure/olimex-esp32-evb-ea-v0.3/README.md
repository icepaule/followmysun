# Olimex ESP32-EVB-EA Rev. L – Schuppendach-Gehäuse v0.3

Parametrisches 3D-Druck-Gehäuse für den **Olimex ESP32-EVB-EA Rev. L** des FollowMySun-Controllers. Es ist für die Montage **innerhalb des Schuppens, über Kopf unter dem Dach** ausgelegt.

## v0.3

- Zugang zu **CON1 + CON2**: zwei 3-polige DG306-5.0-Schraubklemmen / insgesamt sechs Aktuator-Anschlüsse.
- Gemeinsame seitliche Kabeleinführung für die sechs Klemmen: **33,1 × 13,5 mm**.
- Zwei untere Schraubendreher-Servicefenster: je **13 × 14 mm**.
- **Micro-USB / USB-UART1**: **13 × 8,5 mm**.
- **WLAN**: Ø **10,0 mm** durchgehend.
- **PWR1**: **11 × 11 mm**.
- **UEXT/Dupont**: **16 × 7 mm**.
- **RST1** über separaten gedruckten Plunger.
- **Kein CAN-Ausschnitt**.

## Abmessungen

| Merkmal | Maß |
|---|---:|
| Gehäuse ohne Laschen | 94 × 92 × 31 mm |
| Wandstärke | 2,6 mm |
| PCB-Standoff | 4,0 mm |
| WLAN | Ø 10,0 mm |
| PWR1 | 11 × 11 mm |
| UEXT/Dupont | 16 × 7 mm |
| Micro-USB | 13 × 8,5 mm |
| CON1+CON2 Seitenöffnung | 33,1 × 13,5 mm |
| Servicefenster Klemmen | 2 × 13 × 14 mm |
| RST1 Wandbohrung | Ø 4,2 mm |
| Dach-Montagebohrungen | Ø 4,5 mm |

## Dateien

- `olimex_esp32_evb_ea_roof_housing_v0.3.scad` – komplettes parametrisches Modell.
- `build.sh` – rendert Base, Lid, RST-Button und Fit-Test als STL und erzeugt ein ZIP.
- `SOURCE_POSITIONS.md` – verwendete Rev.-L-Koordinaten.
- `MESH_QA.json` – Prüfergebnis der bereits erzeugten Referenz-STLs.

Die gerenderten Referenz-STLs sind wegen ihrer Größe nicht doppelt im Git-Tree abgelegt. Sie lassen sich mit `build.sh` aus der versionierten SCAD-Quelle reproduzieren.

## Bauen

Voraussetzungen: OpenSCAD CLI, `zip`, `sha256sum`.

```bash
cd hardware/enclosure/olimex-esp32-evb-ea-v0.3
chmod +x build.sh
./build.sh
```

Die Ergebnisse liegen danach unter `dist/`.

## Druck

Für den dauerhaften Einbau im Schuppen: **PETG oder ASA**. PLA eignet sich vor allem für den Fit-Test. Startwerte: 0,20 mm Layer, 4 Perimeter, 25–35 % Infill, 5 Top-/Bottom-Layer.

Vor dem großen Druck zuerst `fit_test_v0.3.stl` erzeugen und WLAN-, PWR-, Micro-USB- und Klemmenmaße am realen Aufbau prüfen.

Ausführliche Projektdokumentation: [`docs/housing-esp32-evb.md`](../../../docs/housing-esp32-evb.md).
