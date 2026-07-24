# Olimex ESP32-EVB-EA Solar Panel Controller
# MicroPython 1.27+ ESP32_GENERIC
#
# Features:
# - Astronomische Sonnenwinkel-Berechnung (Azimut-aware Optimum, S-Tilt)
# - MPU-6050 Regelung mit asymmetrischer Hysterese
# - MQTT-Telemetrie + Commands (Manual, MinAngle, Emergency, SetAngle, Recalc)
# - WebGUI (Dashboard + Manual-Buttons + Kalibrierung), nonblocking auf :80
# - WebREPL fuer Fernwartung
# - 3-Layer-Watchdog + UDP-Keepalive + WLAN-Auto-Reconnect
#
# Init-Reihenfolge (MPU-optional): WLAN -> MQTT -> MPU (optional) -> HTTP -> WDT
# Ohne MPU laeuft WebGUI + MQTT + Diagnose weiter, Motor bleibt aus (Sicherheit).

import machine
import time
import network
import gc
import sys
if sys.platform == "esp8266":
    import esp
else:
    class _EspCompat:
        SLEEP_NONE = 0
        @staticmethod
        def sleep_type(*_a, **_kw):
            return 0
    esp = _EspCompat()
import socket
import errno
import math
import uselect
import ujson
import uos
from umqtt.simple import MQTTClient
from mpu6050 import MPU6050

import env
print("env.py geladen")

# =============================================================================
# GLOBALE VARIABLEN
# =============================================================================

sensor = None
rel1 = None
rel2 = None
mqtt = None
wdt = None
http_sock = None

current_angle = None
current_angle_raw = None
angle = 35.0
target = 30.0
tolerance = 2.0
motion_dir = 0
manual_override = False
emergency_mode = False

sunset = 21
sunrise = 8
tz_offset_hours = 2

mqtt_connected = False
last_mqtt_publish = 0
mqtt_publish_interval = 30000
last_mqtt_connect_attempt = 0
_boot_info_published = False
mqtt_reconnect_interval = 60000
last_mqtt_ping = 0
mqtt_ping_interval = 30000

last_successful_publish_ticks = 0
PUBLISH_STALE_MS = 300000

last_ping_sent_token = 0
last_ping_sent_ticks = 0
last_echo_seen_ticks = 0
ECHO_INTERVAL_MS = 60000
ECHO_TIMEOUT_MS = 120000

boot_ticks = 0
SCHEDULED_REBOOT_MS = 21600000

udp_keepalive = None
udp_keepalive_gw = None

system_status = {
    'uptime': 0,
    'heap_free': 0,
    'wifi_rssi': 0,
    'last_error': None,
    'boot_time': None,
    'ntp_sync_count': 0
}

# =============================================================================
# ASTRO
# =============================================================================

def _solar_elevation_at(offset_hours=0.0):
    t = time.localtime()
    doy = t[7]
    local_hour = t[3] + t[4]/60.0 + t[5]/3600.0 + offset_hours
    utc_hour = local_hour - tz_offset_hours
    lat = math.radians(getattr(env, "LATITUDE", 48.066))
    lon = getattr(env, "LONGITUDE", 11.667)
    B = math.radians(360.0/365.0 * (doy - 81))
    decl = math.radians(23.45) * math.sin(B)
    eot_min = 9.87*math.sin(2*B) - 7.53*math.cos(B) - 1.5*math.sin(B)
    solar_time = utc_hour + lon/15.0 + eot_min/60.0
    H = math.radians((solar_time - 12.0) * 15.0)
    sin_elev = math.sin(decl)*math.sin(lat) + math.cos(decl)*math.cos(lat)*math.cos(H)
    sin_elev = max(-1.0, min(1.0, sin_elev))
    return math.degrees(math.asin(sin_elev))

def _solar_position():
    t = time.localtime()
    doy = t[7]
    local_hour = t[3] + t[4]/60.0 + t[5]/3600.0
    utc_hour = local_hour - tz_offset_hours
    lat = math.radians(getattr(env, "LATITUDE", 48.066))
    lon = getattr(env, "LONGITUDE", 11.667)
    B = math.radians(360.0/365.0 * (doy - 81))
    decl = math.radians(23.45) * math.sin(B)
    eot_min = 9.87*math.sin(2*B) - 7.53*math.cos(B) - 1.5*math.sin(B)
    solar_time = utc_hour + lon/15.0 + eot_min/60.0
    H = math.radians((solar_time - 12.0) * 15.0)
    sin_elev = math.sin(decl)*math.sin(lat) + math.cos(decl)*math.cos(lat)*math.cos(H)
    sin_elev = max(-1.0, min(1.0, sin_elev))
    elev = math.asin(sin_elev)
    den = math.cos(elev)*math.cos(lat)
    if abs(den) < 1e-9:
        azi = math.pi
    else:
        cos_azi = (math.sin(decl) - math.sin(elev)*math.sin(lat)) / den
        cos_azi = max(-1.0, min(1.0, cos_azi))
        azi = math.acos(cos_azi)
    if H > 0:
        azi = 2*math.pi - azi
    return math.degrees(elev), math.degrees(azi)


def calculate_optimal_angle():
    try:
        elev_deg, az_deg = _solar_position()
        if elev_deg <= 0:
            return env.MIN_ANGLE
        elev_r = math.radians(elev_deg)
        az_r = math.radians(az_deg)
        tilt_r = math.atan2(-math.cos(az_r) * math.cos(elev_r), math.sin(elev_r))
        tilt_deg = math.degrees(tilt_r)
        if tilt_deg < 0:
            tilt_deg = 0.0
        min_a = env.MIN_ANGLE
        max_a = getattr(env, "MAX_ANGLE", 70.0)
        result = max(min_a, min(max_a, tilt_deg))
        print("Sonne: elev={:.1f} az={:.1f} -> opt={:.1f} -> Ziel={:.1f}".format(
            elev_deg, az_deg, tilt_deg, result))
        return round(result, 1)
    except Exception as e:
        print("Winkel-Berechnung Fehler:", e)
        return env.MIN_ANGLE

def is_night():
    t = time.localtime()
    morning_start = int(getattr(env, "MORNING_START_HOUR", 8))
    try:
        if _solar_elevation_at(0.0) <= 0.0:
            return True
        margin = float(getattr(env, "SUNSET_MARGIN_HOURS", 1.0))
        if _solar_elevation_at(margin) <= 0.0:
            return True
        return False
    except Exception:
        return t[3] < morning_start or t[3] >= sunset

def get_formatted_time():
    try:
        t = time.localtime()
        return "{:02d}.{:02d}.{} {:02d}:{:02d}:{:02d}".format(
            t[2], t[1], t[0], t[3], t[4], t[5]
        )
    except:
        return "Zeitfehler"

def sync_time():
    global system_status, tz_offset_hours
    try:
        import ntptime
        print("NTP-Sync...")
        ntp_servers = ["10.10.12.1", "pool.ntp.org", "de.pool.ntp.org",
                       "time.google.com", "ptbtime1.ptb.de"]
        success = False
        for server in ntp_servers:
            try:
                ntptime.host = server
                ntptime.settime()
                success = True
                system_status['ntp_sync_count'] += 1
                print("NTP OK via", server)
                break
            except Exception as e:
                print("NTP fail", server, ":", e)
        if not success:
            system_status['last_error'] = "NTP sync failed"
            return False

        utc_time = time.localtime()
        year, month, day, hour = utc_time[0], utc_time[1], utc_time[2], utc_time[3]

        def last_sunday_of_month(y, m):
            if m == 12:
                nxt = time.mktime((y+1, 1, 1, 0, 0, 0, 0, 0, 0))
            else:
                nxt = time.mktime((y, m+1, 1, 0, 0, 0, 0, 0, 0))
            last_day = time.localtime(nxt - 86400)[2]
            for d in range(last_day, last_day-7, -1):
                if time.localtime(time.mktime((y, m, d, 0, 0, 0, 0, 0, 0)))[6] == 6:
                    return d
            return last_day

        dst_start = last_sunday_of_month(year, 3)
        dst_end = last_sunday_of_month(year, 10)
        is_dst = False
        if month < 3 or month > 10: is_dst = False
        elif month > 3 and month < 10: is_dst = True
        elif month == 3:
            if day > dst_start: is_dst = True
            elif day == dst_start and hour >= 1: is_dst = True
        elif month == 10:
            if day < dst_end: is_dst = True
            elif day == dst_end and hour < 1: is_dst = True

        tz_offset = 7200 if is_dst else 3600
        tz_offset_hours = 2 if is_dst else 1
        local_ts = time.mktime(utc_time) + tz_offset
        lt = time.localtime(local_ts)
        try:
            machine.RTC().datetime((lt[0], lt[1], lt[2], lt[6], lt[3], lt[4], lt[5], 0))
        except: pass
        if system_status['boot_time'] is None:
            system_status['boot_time'] = get_formatted_time()
        print("Zeit:", get_formatted_time(), "MESZ" if is_dst else "MEZ")
        return True
    except Exception as e:
        print("sync_time err:", e)
        system_status['last_error'] = "NTP: " + str(e)
        return False

# =============================================================================
# CALIB
# =============================================================================

def load_calibration():
    try:
        with open("/calib.json", "r") as f:
            d = ujson.loads(f.read())
        if "SENSOR_OFFSET" in d:
            env.SENSOR_OFFSET = float(d["SENSOR_OFFSET"])
        if "SENSOR_SIGN" in d:
            env.SENSOR_SIGN = int(d["SENSOR_SIGN"])
        print("calib geladen:", d)
    except OSError:
        pass
    except Exception as e:
        print("calib load err:", e)

def save_calibration():
    try:
        d = {
            "SENSOR_OFFSET": getattr(env, "SENSOR_OFFSET", 0.0),
            "SENSOR_SIGN": getattr(env, "SENSOR_SIGN", 1),
        }
        with open("/calib.json", "w") as f:
            f.write(ujson.dumps(d))
        return True
    except Exception as e:
        print("calib save err:", e)
        return False

# =============================================================================
# ACTION HELPERS - benutzt von MQTT- UND HTTP-Handler
# =============================================================================

def action_set_emergency(on):
    """emergency an/aus. Return status string."""
    global emergency_mode, manual_override, target, angle
    on = bool(on)
    if on == emergency_mode:
        return "Emergency unchanged (%s)" % ("on" if on else "off")
    emergency_mode = on
    manual_override = False
    if on:
        target = env.MIN_ANGLE
        _mqtt_pub_debug("Emergency ON")
    else:
        angle = calculate_optimal_angle()
        target = angle if not is_night() else env.MIN_ANGLE
        _mqtt_pub_debug("Emergency OFF")
    try:
        if mqtt_connected and mqtt:
            mqtt.publish("{}/Emergency".format(env.MQTT_TOPIC_SENSOR),
                         "true" if on else "false")
    except: pass
    return "Emergency %s" % ("on" if on else "off")

def action_manual(direction):
    """direction in {'up','down','auto'}."""
    global manual_override, motion_dir
    if emergency_mode:
        return "ignored: emergency active"
    if rel1 is None or rel2 is None:
        return "err: relays not initialized"
    d = direction.strip().lower()
    if d == "up":
        manual_override = True
        rel1.off(); rel2.on(); motion_dir = 1
        _mqtt_pub_debug("Manual: Up")
        return "Manual: Up"
    if d == "down":
        manual_override = True
        rel1.on(); rel2.off(); motion_dir = 2
        _mqtt_pub_debug("Manual: Down")
        return "Manual: Down"
    if d == "auto":
        manual_override = False
        rel1.off(); rel2.off(); motion_dir = 0
        _mqtt_pub_debug("Auto mode")
        return "Auto"
    return "err: unknown dir " + d[:16]

def action_setangle(target_actual):
    """Kalibrierung: aktueller Panel-Winkel = target_actual Grad."""
    global current_angle
    if current_angle_raw is None:
        return "err: no MPU reading yet"
    try:
        target_actual = float(target_actual)
    except Exception:
        return "err: not numeric"
    sign = getattr(env, "SENSOR_SIGN", 1) or 1
    new_offset = current_angle_raw - (target_actual / sign)
    env.SENSOR_OFFSET = new_offset
    save_calibration()
    current_angle = round(sign * (current_angle_raw - new_offset), 1)
    _mqtt_pub_debug("SETANGLE {:.1f} -> offset={:.2f}".format(target_actual, new_offset))
    try: mqtt_publish_sensor_data()
    except: pass
    return "calib: offset={:.2f}, panel=%.1f" % new_offset % target_actual

def action_recalc():
    global angle, target
    angle = calculate_optimal_angle()
    if not emergency_mode and not is_night():
        target = angle
    _mqtt_pub_debug("Recalc angle={:.1f} target={:.1f}".format(angle, target))
    return "recalc: sun=%.1f target=%.1f" % (angle, target)

def action_set_minangle(v):
    global target
    try:
        v = float(v)
    except Exception:
        return "err: not numeric"
    env.MIN_ANGLE = max(0.0, min(70.0, v))
    if emergency_mode or is_night():
        target = env.MIN_ANGLE
    _mqtt_pub_debug("MIN_ANGLE={:.1f}".format(env.MIN_ANGLE))
    return "MIN_ANGLE=%.1f" % env.MIN_ANGLE

def _mqtt_pub_debug(msg):
    try:
        mqtt_publish_debug(msg)
    except: pass

# =============================================================================
# MQTT
# =============================================================================

def mqtt_on_message(topic, msg):
    global last_ping_sent_token, last_echo_seen_ticks
    try:
        t = topic.decode() if isinstance(topic, (bytes, bytearray)) else topic
        m_raw = msg.decode() if isinstance(msg, (bytes, bytearray)) else msg
        if t.endswith("/PING_ECHO"):
            last_echo_seen_ticks = time.ticks_ms()
            try:
                if int(m_raw) == last_ping_sent_token:
                    last_ping_sent_token = 0
            except: pass
            return
        m = m_raw.strip().lower()
        print("MQTT cmd:", t, "=", m)
        if t.endswith("/EMERGENCY"):
            action_set_emergency(m in ("on", "1", "true", "yes"))
        elif t.endswith("/SETANGLE"):
            action_setangle(m_raw.strip())
        elif t.endswith("/RECALC"):
            action_recalc()
        elif t.endswith("/MANUAL"):
            action_manual(m)
        elif t.endswith("/MIN_ANGLE"):
            action_set_minangle(m_raw.strip())
    except Exception as e:
        print("MQTT-Callback err:", e)


def mqtt_connect():
    global mqtt, mqtt_connected, system_status
    try:
        if mqtt:
            try: mqtt.disconnect()
            except: pass
        mqtt = MQTTClient(
            env.MQTT_CLIENT_ID, env.MQTT_SERVER, port=env.MQTT_PORT,
            user=env.MQTT_USER, password=env.MQTT_PASSWORD, keepalive=60
        )
        mqtt.set_callback(mqtt_on_message)
        try:
            mqtt.set_last_will(b"tele/solar/LWT", b"Offline", retain=True, qos=0)
        except Exception as e:
            print("LWT-Setup:", e)
        mqtt.connect()
        mqtt_connected = True
        try:
            mqtt.publish(b"tele/solar/LWT", b"Online", retain=True)
        except: pass
        print("MQTT verbunden")
        cmd_base = getattr(env, 'MQTT_TOPIC_CMD', 'cmnd/solar')
        for sub in ("/EMERGENCY", "/SETANGLE", "/RECALC", "/MANUAL", "/MIN_ANGLE"):
            try: mqtt.subscribe(cmd_base + sub)
            except Exception as e: print("Sub-err", sub, e)
        try:
            mqtt.subscribe(b"tele/solar/PING_ECHO")
        except: pass
        mqtt_publish_status("online", retain=True)
        try: _publish_boot_info_once()
        except Exception as e: print("boot-info err:", e)
        return True
    except Exception as e:
        mqtt_connected = False
        system_status['last_error'] = "MQTT connect: " + str(e)
        print("MQTT-Verb fehlgeschlagen:", e)
        return False

def _publish_boot_info_once():
    global _boot_info_published
    if _boot_info_published or not mqtt_connected:
        return
    try:
        with open("_boot_info.txt", "r") as f:
            line = f.read().strip()
    except OSError:
        line = "rc=UNK code=-1 heap=0 t=0"
    try:
        t = time.localtime()
        ts = "{:02d}.{:02d}.{:04d} {:02d}:{:02d}:{:02d}".format(
            t[2], t[1], t[0], t[3], t[4], t[5])
    except: ts = ""
    dev = getattr(env, "MQTT_CLIENT_ID", "esp_solar")
    payload = '{"Time":"'+ts+'","Boot":"'+line+'","Device":"'+dev+'"}'
    try:
        mqtt.publish("tele/solar/BOOT", payload, retain=True)
        _boot_info_published = True
    except Exception as e:
        print("BOOT-publish err:", e)

def _get_state_snapshot():
    """Baut das JSON-Datenobjekt fuer MQTT UND HTTP."""
    try:
        wlan = network.WLAN(network.STA_IF)
        rssi = wlan.status('rssi') if wlan.isconnected() else -99
        ip = wlan.ifconfig()[0] if wlan.isconnected() else "0.0.0.0"
    except Exception:
        rssi = -99; ip = "0.0.0.0"
    return {
        "Time": get_formatted_time(),
        "SENSOR": {
            "PanelAngle": round(current_angle, 1) if current_angle is not None else None,
            "PanelAngleRaw": round(current_angle_raw, 1) if current_angle_raw is not None else None,
            "TargetAngle": round(target, 1),
            "SunAngle": round(angle, 1),
            "MinAngle": round(env.MIN_ANGLE, 1),
            "MaxAngle": round(getattr(env, "MAX_ANGLE", 70.0), 1),
            "SensorOffset": getattr(env, "SENSOR_OFFSET", 0.0),
            "SensorSign": getattr(env, "SENSOR_SIGN", 1),
            "Tolerance": tolerance,
            "Motion": motion_dir,
            "MotionText": ["Stopp", "Hoch", "Runter"][motion_dir],
            "Manual": manual_override,
            "Emergency": emergency_mode,
            "IsNight": is_night(),
            "MpuOk": sensor is not None,
        },
        "SYSTEM": {
            "Uptime": time.ticks_ms() // 1000,
            "HeapFree": gc.mem_free(),
            "WiFiRSSI": rssi,
            "NTPSyncCount": system_status['ntp_sync_count'],
            "BootTime": system_status['boot_time'],
            "LastError": system_status['last_error'],
        },
        "STATUS": {"Online": True, "IP": ip},
    }

def mqtt_publish_sensor_data():
    global system_status, last_successful_publish_ticks
    if not mqtt_connected:
        return False
    try:
        gc.collect()
        payload = ujson.dumps(_get_state_snapshot())
        mqtt.publish(env.MQTT_TOPIC_SENSOR, payload)
        payload = None
        gc.collect()
        last_successful_publish_ticks = time.ticks_ms()
        return True
    except Exception as e:
        print("MQTT-pub err:", e)
        system_status['last_error'] = "MQTT publish: " + str(e)
        return False

def mqtt_publish_status(status, retain=False):
    if not mqtt_connected: return False
    try:
        ip = network.WLAN(network.STA_IF).ifconfig()[0] if network.WLAN(network.STA_IF).isconnected() else "unknown"
        d = {"Time": get_formatted_time(), "Status": status,
             "Device": env.MQTT_CLIENT_ID, "IP": ip}
        mqtt.publish("stat/{}/STATUS".format(env.MQTT_CLIENT_ID), ujson.dumps(d), retain=retain)
        return True
    except Exception as e:
        print("MQTT-status err:", e); return False

def mqtt_publish_debug(message):
    if not mqtt_connected: return False
    try:
        d = {"Time": get_formatted_time(), "Debug": message, "Device": env.MQTT_CLIENT_ID}
        topic = getattr(env, 'MQTT_TOPIC_DEBUG', 'stat/solar/DEBUG')
        mqtt.publish(topic, ujson.dumps(d))
        return True
    except Exception as e:
        print("MQTT-dbg err:", e); return False

def mqtt_check_connection():
    global mqtt_connected, last_mqtt_connect_attempt, last_mqtt_ping
    now = time.ticks_ms()
    if not mqtt_connected and time.ticks_diff(now, last_mqtt_connect_attempt) > mqtt_reconnect_interval:
        print("MQTT reconnect...")
        last_mqtt_connect_attempt = now
        mqtt_connect()
    if mqtt_connected:
        try: mqtt.check_msg()
        except Exception as e:
            print("check_msg err:", e); mqtt_connected = False
    if mqtt_connected and time.ticks_diff(now, last_mqtt_ping) > mqtt_ping_interval:
        try:
            mqtt.ping(); last_mqtt_ping = now
        except:
            print("MQTT ping lost"); mqtt_connected = False

# =============================================================================
# WEB SERVER (nonblocking, im Main-Loop)
# =============================================================================

HTML_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Solar</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,sans-serif;margin:0;padding:1em;background:#f7f7fa;color:#222}
h1{font-size:1.3em;margin:0 0 .8em}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:.6em;margin-bottom:1.2em}
.card{background:#fff;border:1px solid #ddd;border-radius:8px;padding:.6em .8em}
.card .l{font-size:.75em;color:#666;text-transform:uppercase;letter-spacing:.05em}
.card .v{font-size:1.4em;font-weight:600;margin-top:.1em}
.card.warn{border-color:#c94}
.card.ok{border-color:#4a7}
.card.err{border-color:#c33;background:#fef}
button{font-size:1em;padding:.6em 1em;border-radius:6px;border:1px solid #888;background:#eee;cursor:pointer;margin:.15em}
button:hover{background:#ddd}
button.primary{background:#358;color:#fff;border-color:#246}
button.danger{background:#c33;color:#fff;border-color:#911}
button.warn{background:#c94;color:#fff;border-color:#963}
section{background:#fff;border-radius:8px;padding:.8em 1em;margin-bottom:1em;border:1px solid #ddd}
section h2{font-size:.95em;margin:0 0 .5em;color:#456}
input[type=number]{font-size:1em;padding:.4em;width:5em;border:1px solid #888;border-radius:4px}
.foot{font-size:.75em;color:#888;margin-top:1em;text-align:center}
</style></head><body>
<h1>PV-Tracker (Olimex ESP32-EVB)</h1>
<div class="grid" id="g"></div>
<section><h2>Motor manuell</h2>
<button onclick="cmd('/api/manual','up')">Hoch</button>
<button onclick="cmd('/api/manual','down')">Runter</button>
<button class="primary" onclick="cmd('/api/manual','auto')">Auto</button>
</section>
<section><h2>Notfall</h2>
<button class="danger" onclick="cmd('/api/emergency','on')">EMERGENCY ON</button>
<button onclick="cmd('/api/emergency','off')">Emergency Off</button>
<button class="warn" onclick="cmd('/api/recalc','')">Recalc</button>
</section>
<section><h2>Kalibrierung / Grenzen</h2>
Panel steht auf <input id="sa" type="number" step="0.1" value="45"> Grad
<button onclick="cmd('/api/setangle',document.getElementById('sa').value)">SetAngle</button>
<br style="margin-top:.4em">
MIN_ANGLE <input id="ma" type="number" step="0.1" value="32"> Grad
<button onclick="cmd('/api/minangle',document.getElementById('ma').value)">Setzen</button>
</section>
<div id="log" style="font-size:.75em;color:#666"></div>
<div class="foot">Auto-Refresh 4s / <a href="javascript:pull()">Refresh</a></div>
<script>
function el(k,v,c){return '<div class="card '+(c||'')+'"><div class="l">'+k+'</div><div class="v">'+v+'</div></div>'}
async function pull(){
 try{let r=await fetch('/api/state'); let d=await r.json();
  let s=d.SENSOR, y=d.SYSTEM, st=d.STATUS;
  let g='';
  g+=el('Panel', s.PanelAngle==null?'--':s.PanelAngle+'°', s.MpuOk?'':'err');
  g+=el('Ziel', s.TargetAngle+'°');
  g+=el('Sonne', s.SunAngle+'°');
  g+=el('Motor', s.MotionText, s.Motion?'warn':'');
  g+=el('Emergency', s.Emergency?'AN':'aus', s.Emergency?'err':'ok');
  g+=el('Manual', s.Manual?'AN':'aus', s.Manual?'warn':'');
  g+=el('IsNight', s.IsNight?'ja':'nein');
  g+=el('MinAngle', s.MinAngle+'°');
  g+=el('MaxAngle', s.MaxAngle+'°');
  g+=el('RSSI', y.WiFiRSSI+' dBm');
  g+=el('Heap', Math.round(y.HeapFree/1024)+' kB');
  g+=el('Uptime', Math.round(y.Uptime/60)+' min');
  g+=el('IP', st.IP);
  g+=el('MPU', s.MpuOk?'OK':'NC', s.MpuOk?'ok':'err');
  if(y.LastError) g+=el('LastError', y.LastError, 'err');
  document.getElementById('g').innerHTML=g;
 }catch(e){document.getElementById('log').textContent='err '+e;}
}
async function cmd(u,v){
 try{
  let f=new FormData(); if(v!==undefined&&v!=='') f.append('v',v);
  let r=await fetch(u,{method:'POST',body:f});
  let t=await r.text();
  document.getElementById('log').textContent=u+' -> '+t;
  setTimeout(pull,300);
 }catch(e){document.getElementById('log').textContent='err '+e;}
}
pull(); setInterval(pull,4000);
</script></body></html>"""

def _http_start():
    global http_sock
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', 80))
        s.listen(2)
        s.setblocking(False)
        http_sock = s
        print("HTTP-Server auf :80")
    except Exception as e:
        print("HTTP start err:", e)
        http_sock = None

def _http_send(cl, code, ctype, body):
    if isinstance(body, str):
        body = body.encode('utf-8')
    cl.sendall(("HTTP/1.0 %d OK\r\nContent-Type: %s\r\nConnection: close\r\nCache-Control: no-store\r\nContent-Length: %d\r\n\r\n"
                % (code, ctype, len(body))).encode('utf-8'))
    cl.sendall(body)

def _parse_form(body):
    """Sehr einfacher application/x-www-form-urlencoded parser (nur k=v&...)."""
    out = {}
    for part in body.split('&'):
        if '=' in part:
            k, v = part.split('=', 1)
            v = v.replace('+', ' ')
            # minimal urldecode fuer unsere Zwecke (nur %HH)
            try:
                while '%' in v:
                    i = v.index('%')
                    v = v[:i] + chr(int(v[i+1:i+3], 16)) + v[i+3:]
            except: pass
            out[k] = v
    return out

def _http_handle_request(method, path, headers, body):
    """Return (code, ctype, body_str)."""
    if method == 'GET' and (path == '/' or path == '/index.html'):
        return 200, 'text/html; charset=utf-8', HTML_PAGE
    if method == 'GET' and path == '/api/state':
        return 200, 'application/json', ujson.dumps(_get_state_snapshot())
    if method == 'POST' and path.startswith('/api/'):
        form = _parse_form(body) if body else {}
        v = form.get('v', '')
        # Boundary-Fall multipart (aus JS FormData): sehr grober Extract
        if not v and 'multipart/form-data' in headers.get('content-type', ''):
            # form data: ...\r\nContent-Disposition: form-data; name="v"\r\n\r\n<val>\r\n--boundary...
            try:
                idx = body.find('name="v"')
                if idx != -1:
                    start = body.find('\r\n\r\n', idx) + 4
                    end = body.find('\r\n', start)
                    v = body[start:end]
            except: pass
        if path == '/api/manual':
            return 200, 'text/plain', action_manual(v or 'auto')
        if path == '/api/emergency':
            return 200, 'text/plain', action_set_emergency(v.lower() in ('on','1','true','yes'))
        if path == '/api/recalc':
            return 200, 'text/plain', action_recalc()
        if path == '/api/setangle':
            return 200, 'text/plain', action_setangle(v)
        if path == '/api/minangle':
            return 200, 'text/plain', action_set_minangle(v)
    return 404, 'text/plain', 'not found'

def _http_poll():
    if http_sock is None:
        return
    try:
        cl, addr = http_sock.accept()
    except OSError:
        return
    try:
        cl.settimeout(2.0)
        raw = b''
        # Header lesen bis \r\n\r\n
        for _ in range(20):
            try:
                chunk = cl.recv(1024)
            except OSError:
                break
            if not chunk: break
            raw += chunk
            if b'\r\n\r\n' in raw:
                break
            if len(raw) > 8192: break
        if not raw:
            return
        head_end = raw.find(b'\r\n\r\n')
        if head_end == -1:
            _http_send(cl, 400, 'text/plain', 'bad request'); return
        head = raw[:head_end].decode('utf-8', 'ignore')
        body = raw[head_end+4:].decode('utf-8', 'ignore')
        lines = head.split('\r\n')
        parts = lines[0].split(' ')
        if len(parts) < 2:
            _http_send(cl, 400, 'text/plain', 'bad'); return
        method, path = parts[0], parts[1]
        headers = {}
        for ln in lines[1:]:
            if ':' in ln:
                k, v = ln.split(':', 1)
                headers[k.strip().lower()] = v.strip()
        # ggf. weiterlesen wenn Content-Length groesser als bereits gelesen
        clen = 0
        try: clen = int(headers.get('content-length', '0'))
        except: pass
        if clen and len(body) < clen:
            need = clen - len(body)
            try:
                more = cl.recv(min(need, 4096))
                if more: body += more.decode('utf-8', 'ignore')
            except: pass
        code, ctype, resp = _http_handle_request(method, path, headers, body)
        _http_send(cl, code, ctype, resp)
    except Exception as e:
        print("HTTP handle err:", e)
        try: _http_send(cl, 500, 'text/plain', 'srv err')
        except: pass
    finally:
        try: cl.close()
        except: pass

# =============================================================================
# MAIN LOOP
# =============================================================================

def loop():
    global current_angle, current_angle_raw, motion_dir, manual_override, angle, target
    global last_mqtt_publish, system_status, mqtt_connected, last_successful_publish_ticks
    global last_ping_sent_token, last_ping_sent_ticks, last_echo_seen_ticks

    last_sensor_read = 0
    last_angle_calc = 0
    last_time_sync = 0
    last_print_time = 0
    last_printed_angle = None
    last_gc = 0
    last_sleep_check = 0
    last_keepalive = 0
    last_wlan_check = 0
    WLAN_CHECK_INTERVAL_MS = 30000

    SENSOR_INTERVAL_MS = 150
    PRINT_INTERVAL_MS = 2000
    PRINT_DELTA_DEG = 0.5
    START_TOLERANCE = 2.0
    STOP_TOLERANCE = 0.5

    while True:
        try:
            now = time.ticks_ms()

            # WLAN-Assoziation pruefen
            if time.ticks_diff(now, last_wlan_check) > WLAN_CHECK_INTERVAL_MS:
                last_wlan_check = now
                try:
                    _wlan = network.WLAN(network.STA_IF)
                    if not _wlan.isconnected():
                        print("WLAN getrennt - reconnect", env.WIFI_SSID)
                        mqtt_connected = False
                        try: _wlan.disconnect()
                        except: pass
                        try:
                            _wlan.active(True)
                            _wlan.connect(env.WIFI_SSID, env.WIFI_PASSWORD)
                        except Exception as e:
                            print("WLAN reconnect err:", e)
                except Exception as e:
                    print("WLAN-Check err:", e)

            # Stale-Publish Watchdog
            if last_successful_publish_ticks != 0 and time.ticks_diff(now, last_successful_publish_ticks) > PUBLISH_STALE_MS:
                stale = time.ticks_diff(now, last_successful_publish_ticks)
                print("stale-watchdog %dms -> reset" % stale)
                try:
                    with open("_reset_info.txt", "w") as f:
                        f.write("stale %dms heap=%d\n" % (stale, gc.mem_free()))
                except: pass
                try: rel1.off(); rel2.off()
                except: pass
                time.sleep(1); machine.reset()

            # Echo-Watchdog
            if mqtt_connected:
                if time.ticks_diff(now, last_ping_sent_ticks) > ECHO_INTERVAL_MS:
                    try:
                        last_ping_sent_token = now & 0x3FFFFFFF or 1
                        mqtt.publish(b"tele/solar/PING_ECHO", str(last_ping_sent_token).encode())
                        last_ping_sent_ticks = now
                        if last_echo_seen_ticks == 0:
                            last_echo_seen_ticks = now
                    except Exception as e:
                        print("echo-pub err:", e)
                if last_echo_seen_ticks != 0 and time.ticks_diff(now, last_echo_seen_ticks) > ECHO_TIMEOUT_MS:
                    el = time.ticks_diff(now, last_echo_seen_ticks)
                    print("echo-watchdog %dms -> reset" % el)
                    try:
                        with open("_reset_info.txt", "w") as f:
                            f.write("echo %dms heap=%d\n" % (el, gc.mem_free()))
                    except: pass
                    try: rel1.off(); rel2.off()
                    except: pass
                    time.sleep(1); machine.reset()

            # Scheduled 6h reboot
            if boot_ticks != 0 and time.ticks_diff(now, boot_ticks) > SCHEDULED_REBOOT_MS:
                print("scheduled reboot")
                try:
                    with open("_reset_info.txt", "w") as f:
                        f.write("scheduled heap=%d\n" % gc.mem_free())
                except: pass
                try: rel1.off(); rel2.off()
                except: pass
                time.sleep(1); machine.reset()

            mqtt_check_connection()

            # HTTP (nonblocking)
            _http_poll()

            # NTP alle 24h
            if time.ticks_diff(now, last_time_sync) > 86400000:
                sync_time(); last_time_sync = now

            # Sensor lesen (nur wenn MPU vorhanden)
            if sensor is not None and time.ticks_diff(now, last_sensor_read) > SENSOR_INTERVAL_MS:
                try:
                    r = sensor.get_angle_roll()
                    if r is not None:
                        current_angle_raw = r
                        sign = getattr(env, "SENSOR_SIGN", 1)
                        offset = getattr(env, "SENSOR_OFFSET", 0.0)
                        current_angle = round(sign * (r - offset), 1)
                        should_print = (last_printed_angle is None
                                        or abs(current_angle - last_printed_angle) >= PRINT_DELTA_DEG
                                        or time.ticks_diff(now, last_print_time) > PRINT_INTERVAL_MS)
                        if should_print:
                            print("Sensor: %.1f (Ziel: %.1f)" % (current_angle, target))
                            last_printed_angle = current_angle
                            last_print_time = now
                    last_sensor_read = now
                except Exception as e:
                    print("sensor err:", e)
                    system_status['last_error'] = "sensor: " + str(e)

            # Recalc alle 10 min
            if time.ticks_diff(now, last_angle_calc) > 600000:
                angle = calculate_optimal_angle()
                if emergency_mode: target = env.MIN_ANGLE
                elif is_night(): target = env.MIN_ANGLE
                else: target = angle
                last_angle_calc = now
                mqtt_publish_debug("Angle recalc: Sun=%.1f Target=%.1f" % (angle, target))

            # Publish alle 30s
            if time.ticks_diff(now, last_mqtt_publish) > mqtt_publish_interval:
                if mqtt_connected:
                    mqtt_publish_sensor_data()
                last_mqtt_publish = now

            # Motor-Control - NUR wenn Sensor da + Wert vorhanden
            old_dir = motion_dir
            if sensor is not None and not manual_override and current_angle is not None:
                diff = current_angle - target
                if motion_dir == 0:
                    if abs(diff) > START_TOLERANCE:
                        if diff > 0:
                            rel1.on(); rel2.off(); motion_dir = 2
                            mqtt_publish_debug("Motor: Runter (diff=%.1f)" % diff)
                        else:
                            rel1.off(); rel2.on(); motion_dir = 1
                            mqtt_publish_debug("Motor: Hoch (diff=%.1f)" % diff)
                else:
                    overshot = (motion_dir == 2 and diff < 0) or (motion_dir == 1 and diff > 0)
                    if abs(diff) < STOP_TOLERANCE or overshot:
                        rel1.off(); rel2.off(); motion_dir = 0
                        mqtt_publish_debug("Motor: Stopp %s" % ("(overshoot)" if overshot else ""))
            elif sensor is not None and not manual_override:
                if motion_dir != 0:
                    rel1.off(); rel2.off(); motion_dir = 0
                    print("Motor: Stopp (kein Sensorwert)")
            # sensor is None: kein Motor-Handling, aktiver Manual bleibt bestehen

            if old_dir != motion_dir and mqtt_connected:
                mqtt_publish_sensor_data()

            if time.ticks_diff(now, last_gc) > 30000:
                gc.collect(); last_gc = now

            if udp_keepalive is not None and time.ticks_diff(now, last_keepalive) > 1000:
                try: udp_keepalive.sendto(b'.', (udp_keepalive_gw, 9))
                except: pass
                last_keepalive = now

            if wdt is not None:
                wdt.feed()

            time.sleep(0.05)

        except Exception as e:
            print("Loop err:", e)
            system_status['last_error'] = "Loop: " + str(e)
            try: rel1.off(); rel2.off(); motion_dir = 0
            except: pass
            time.sleep(1)

# =============================================================================
# INIT (WLAN zuerst, MPU optional)
# =============================================================================

def init():
    global sensor, rel1, rel2, angle, target, wdt
    global udp_keepalive, udp_keepalive_gw
    global last_successful_publish_ticks, boot_ticks

    print("Init...")
    gc.collect()
    last_successful_publish_ticks = time.ticks_ms()
    boot_ticks = time.ticks_ms()
    load_calibration()

    # 1) Relays initialisieren (safe fail = weiter ohne)
    try:
        rel1 = machine.Pin(env.PIN_RELAY1, machine.Pin.OUT)
        rel2 = machine.Pin(env.PIN_RELAY2, machine.Pin.OUT)
        rel1.off(); rel2.off()
        print("Relays init OK")
    except Exception as e:
        print("Relay init err:", e)

    # 2) WLAN zuerst - damit Remote-Zugang immer garantiert ist
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        hn = getattr(env, "HOSTNAME", "solar")
        wlan.config(dhcp_hostname=hn)
    except Exception as e:
        print("hostname err:", e)
    static = getattr(env, "STATIC_IP", None)
    if static:
        try: wlan.ifconfig(static)
        except Exception as e: print("static IP err:", e)
    if wlan.isconnected():
        try:
            cur = wlan.config('essid')
            if cur != env.WIFI_SSID:
                wlan.disconnect(); time.sleep_ms(500)
        except: pass
    if not wlan.isconnected():
        print("WLAN connect:", env.WIFI_SSID)
        wlan.connect(env.WIFI_SSID, env.WIFI_PASSWORD)
        for i in range(30):
            if wlan.isconnected(): break
            print(".", end=""); time.sleep(1)
        print()
    if not wlan.isconnected():
        print("WLAN FAIL - init trotzdem weiter fuer Diagnose")
    else:
        print("WLAN OK:", wlan.ifconfig()[0])
        try: udp_keepalive = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except: udp_keepalive = None
        try: udp_keepalive_gw = wlan.ifconfig()[2]
        except: udp_keepalive_gw = None

    # 3) NTP + MQTT (nur wenn WLAN da)
    if wlan.isconnected():
        sync_time()
        mqtt_connect()

    # 4) MPU-6050 optional
    try:
        i2c = machine.SoftI2C(scl=machine.Pin(env.PIN_I2C_SCL),
                              sda=machine.Pin(env.PIN_I2C_SDA), freq=100000)
        devs = i2c.scan()
        if devs:
            print("I2C-Devices:", [hex(d) for d in devs])
        sensor = MPU6050(i2c)
        print("MPU-6050 init OK")
    except Exception as e:
        print("MPU init err (weiter ohne):", e)
        sensor = None
        system_status['last_error'] = "MPU: " + str(e)
        try:
            if mqtt_connected:
                mqtt_publish_debug("MPU init fail: " + str(e))
        except: pass

    # 5) HTTP-Server (nur wenn WLAN da)
    if wlan.isconnected():
        _http_start()

    # 6) Initial Sun-Angle
    angle = calculate_optimal_angle()
    if emergency_mode: target = env.MIN_ANGLE
    elif is_night(): target = env.MIN_ANGLE
    else: target = angle
    print("Ziel initial: %.1f" % target)

    # 7) Watchdog
    try:
        wdt = machine.WDT(timeout=30000)  # ESP32: 30s statt 3s (mehr Toleranz fuer HTTP-Requests)
        print("WDT aktiv 30s")
    except Exception as e:
        print("WDT err:", e); wdt = None

    return True

if init():
    print("System bereit")
    loop()
else:
    print("Init fehlgeschlagen")
    try:
        rel1 = machine.Pin(env.PIN_RELAY1, machine.Pin.OUT)
        rel2 = machine.Pin(env.PIN_RELAY2, machine.Pin.OUT)
        rel1.off(); rel2.off()
    except: pass
