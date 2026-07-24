# env.example.py - Olimex ESP32-EVB-EA Solar-Tracker
# Kopieren nach env.py und mit den echten Werten fuellen.
# env.py NIEMALS in das Git-Repo committen (steht in .gitignore).

# ------- WLAN -------
WIFI_SSID     = "DEIN_WLAN"
WIFI_PASSWORD = "DEIN_PASSWORT"

# ------- MQTT (im selben VLAN wie der ESP, damit keine Firewall zwischen) -------
MQTT_SERVER    = "192.168.x.x"
MQTT_PORT      = 1883
MQTT_USER      = "user"
MQTT_PASSWORD  = "pass"
MQTT_CLIENT_ID = "esp_solar"
MQTT_TOPIC_SET    = "solar/panel/set"
MQTT_TOPIC_SENSOR = "tele/solar/SENSOR"
MQTT_TOPIC_DEBUG  = "stat/solar/DEBUG"
MQTT_TOPIC_CMD    = "cmnd/solar"

# ------- Relais-Pins Olimex ESP32-EVB(-EA) -------
# On-board fest verdrahtet:
#   REL1 -> GPIO32, REL2 -> GPIO33 (aktiv-HIGH, NPN-getrieben)
# 10 A / 250 VAC Wechsler mit COM/NO/NC-Klemmen.
PIN_RELAY1 = 32        # K1 = Motor Runter (rel1.on() = down)
PIN_RELAY2 = 33        # K2 = Motor Hoch   (rel2.on() = up)

# ------- I2C fuer MPU-6050 am UEXT -------
# Olimex UEXT-Konnektor (10-pol IDC), Standard-Belegung:
#   Pin 1 +3.3V, Pin 2 GND, Pin 3 (SCL=GPIO16), Pin 4 (SDA=GPIO13)
# MPU-6050 direkt am UEXT andocken.
PIN_I2C_SDA = 13
PIN_I2C_SCL = 16
I2C_BUS_ID  = 0

# ------- WebREPL -------
USE_WEBREPL      = True
WEBREPL_PASSWORD = "wechseln"    # min 4 Zeichen

# ------- WebGUI / HTTP -------
# HTTP-Server auf :80 wird bei is_connected()=True automatisch gestartet
# (siehe solar_main.py -> _http_start()).

# ------- Netzwerk-Identifikation -------
HOSTNAME = "solar"

# Optional: statische IP (auskommentiert -> DHCP)
# STATIC_IP = ("10.10.12.55", "255.255.255.0", "10.10.12.1", "10.10.12.1")

# Status-LED: None -> keine LED
LED_PIN = None
LED_ACTIVE_LOW = False

# ------- Sensor-Kalibrierung MPU-6050 -------
# Bei Hardware-Tausch nachkalibrieren:
#   1. Panel in bekannten Winkel bringen, echten Winkel messen
#   2. Ueber MQTT publish cmnd/solar/SETANGLE <winkel_grad>  (oder Web-GUI)
#      -> Firmware rechnet SENSOR_OFFSET selbst aus + persistiert /calib.json
SENSOR_OFFSET = 0.0
SENSOR_SIGN   = 1

# ------- Mechanische Endlagen -------
MIN_ANGLE = 32.0       # Panel-Grad wenn Aktuator eingefahren (Dachneigung)
MAX_ANGLE = 60.0       # Panel-Grad wenn Aktuator voll ausgefahren

# ------- Standort (fuer astronomische Sonnenstand-Berechnung) -------
LATITUDE      = 48.066    # Beispiel: Ottobrunn
LONGITUDE     = 11.667
PANEL_AZIMUTH = 180.0     # 180 = Sued-ausgerichtet

# ------- Tracker Tagesfenster -------
MORNING_START_HOUR  = 8    # nur Fallback; primaer wird astronomisch berechnet
SUNSET_MARGIN_HOURS = 1.0  # x Stunden vor Sonnenuntergang -> auf MIN_ANGLE
