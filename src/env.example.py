# env.py - Konfiguration fuer FollowMySun (ESP12F + MPU-6050)
# ============================================================
# Datei lokal kopieren als `env.py` und Werte einfuellen.
# `env.py` darf NICHT ins Git-Repository commitet werden (.gitignore).

# === WLAN ===
WIFI_SSID     = "DEIN_WLAN_NAME"
WIFI_PASSWORD = "DEIN_WLAN_PASSWORT"

# === MQTT-Broker ===
MQTT_SERVER   = "192.168.1.10"      # IP des Brokers
MQTT_PORT     = 1883
MQTT_USER     = "user"
MQTT_PASSWORD = "passwort"
MQTT_CLIENT_ID = "esp_solar"

# === MQTT-Topics ===
MQTT_TOPIC_SET    = "javascript.0.mqtt.0.solar/panel/set"
MQTT_TOPIC_SENSOR = "tele/solar/SENSOR"
MQTT_TOPIC_DEBUG  = "stat/solar/DEBUG"
# Commands von HA/NodeRed an den ESP. Empfohlen mit retain=True senden,
# damit der Zustand einen ESP-Reboot ueberlebt.
# Bekannte Subtopics:
#   {MQTT_TOPIC_CMD}/EMERGENCY  payload "on"|"off"  -> Panel sofort flach
MQTT_TOPIC_CMD    = "cmnd/solar"

# === Hardware: Relais-Pins (ESP12F-Relay-X4 v1.2) ===
PIN_RELAY1 = 16        # K1 = Motor Runter  (rel1.on() = einfahren)
PIN_RELAY2 = 14        # K2 = Motor Hoch    (rel2.on() = ausfahren)

# === Hardware: I2C fuer MPU-6050 ===
PIN_I2C_SDA = 4        # GPIO4 / D2
PIN_I2C_SCL = 5        # GPIO5 / D1

# === OLED 0.66" SSD1306 64x48 (optional, parallel am I2C-Bus) ===
OLED_ENABLED = False   # auf True wenn Display physisch dran ist
OLED_ADDRESS = 0x3D    # bei vielen Modulen 0x3C - mit i2c.scan() pruefen
OLED_WIDTH   = 64
OLED_HEIGHT  = 48

# === Sensor-Kalibrierung MPU-6050 ===
# Echter Panel-Winkel zur Horizontalen = SENSOR_SIGN * (raw - SENSOR_OFFSET)
#
# Einmessverfahren:
#   1. Aktuator komplett einfahren, Panel liegt auf Dach (z.B. 32 Grad).
#   2. Roh-Wert ablesen (MQTT-Topic tele/solar/SENSOR/PanelAngleRaw).
#   3. SENSOR_OFFSET = raw - 32  (wenn SIGN = +1)
#   4. Aktuator voll ausfahren, Roh-Wert ablesen.
#   5. Wenn ausgefahren > eingefahren -> SIGN = +1. Sonst SIGN = -1.
SENSOR_OFFSET = 87.3   # Beispiel - bitte selbst einmessen
SENSOR_SIGN   = 1

# === Mechanische Endlagen (in echten Grad zur Horizontalen) ===
MIN_ANGLE = 32.0       # Aktuator eingefahren = Dachneigung
MAX_ANGLE = 58.7       # Aktuator voll ausgefahren = bitte einmessen

# === WebREPL (Remote-Code-Update ueber's WLAN) ===
USE_WEBREPL      = True
WEBREPL_PASSWORD = "dein_webrepl_passwort"   # 4-9 Zeichen

# === Netzwerk-Identifikation ===
HOSTNAME = "solar"     # ergibt solar.fritz.box (bei FritzBox)

# Optional: statische IP (auskommentiert -> DHCP)
# STATIC_IP = ("192.168.1.42", "255.255.255.0", "192.168.1.1", "192.168.1.1")
