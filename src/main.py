import time
import pycom
import socket
import ubinascii
from network import WLAN, LoRa
from lib.mqtt import MQTTClient
from lib.pycoproc_2 import Pycoproc
from lib.L76GNSS import L76GNSS

print("=== TRACKER SAE501 - VERSION 3 (WiFi + LoRaWAN) ===")

# =====================================================================
# CONFIGURATION
# =====================================================================

# Mode de transmission :
#   "WIFI"
#   "LORA"
MODE = "LORA"

# --- WiFi / MQTT (mode "WIFI") ---
WIFI_SSID = "<votre SSID WiFi>"
WIFI_PASS = "<votre mot de passe WiFi>"
MQTT_BROKER = "<votre broker MQTT>"
MQTT_PORT = 1883
MQTT_TOPIC = "<votre topic MQTT>"
CLIENT_ID = "<votre client ID MQTT>"
WIFI_INTERVAL = 5 # secondes entre deux publications MQTT

# --- LoRaWAN OTAA (mode "LORA") ---
# Valeurs copiees depuis la page du device sur TTN, format hex MSB, sans espaces.
DEV_EUI = "<DEV_EUI>"                   # DevEUI  (MAC LoRa du FiPy)
APP_EUI = "<APP_EUI>"                   # JoinEUI
APP_KEY = "<APP_KEY>"   # AppKey  (32 caracteres hex)
LORA_PORT = 1            # FPort des uplinks
LORA_DR = 5              # DR5 = SF7 en EU868 (le plus court en temps d'antenne)
LORA_INTERVAL = 150      # secondes entre deux uplinks (voir Fair Use Policy TTN)

# Envoyer une position par defaut quand le GPS n'a pas de fix.
SEND_DEFAULT_POS = False
DEFAULT_LAT = 48.07703
DEFAULT_LON = 7.371032

# Couleurs de la LED RGB (etat du tracker)
LED_OFF = 0x000000
LED_BLUE = 0x00007f      # connexion en cours
LED_GREEN = 0x007f00     # message envoye
LED_ORANGE = 0x7f3f00    # pas de fix GPS
LED_RED = 0x7f0000       # erreur


# =====================================================================
# FONCTIONS COMMUNES
# =====================================================================

def led(color):
    pycom.rgbled(color)


def read_gps(gps):
    """Lit les coordonnees GPS avec gestion d'erreur.
    Retourne (lat, lon) ou (None, None)."""
    try:
        coord = gps.coordinates(debug=False)
        if coord is not None and coord != (None, None):
            lat, lon = coord   # la librairie renvoie (latitude, longitude)
            if lat is not None and lon is not None:
                return lat, lon
    except Exception as e:
        print("Erreur GPS :", e)
    return None, None


def get_position(gps):
    """Renvoie (lat, lon) du GPS, la position par defaut si autorisee,
    ou (None, None) s'il n'y a rien a envoyer."""
    lat, lon = read_gps(gps)
    if lat is not None and lon is not None:
        return lat, lon
    if SEND_DEFAULT_POS:
        print("Pas de fix GPS, utilisation de la position par defaut")
        return DEFAULT_LAT, DEFAULT_LON
    print("Pas encore de fix GPS...")
    led(LED_ORANGE)
    return None, None


# =====================================================================
# MODE WIFI / MQTT
# =====================================================================

def connect_wifi():
    """Se connecte au WiFi avec reessai automatique."""
    wlan = WLAN(mode=WLAN.STA)
    while not wlan.isconnected():
        try:
            print("Tentative de connexion WiFi...")
            wlan.connect(WIFI_SSID, auth=(WLAN.WPA2, WIFI_PASS), timeout=10000)
            for _ in range(20):
                if wlan.isconnected():
                    break
                time.sleep(0.5)
        except Exception as e:
            print("Erreur WiFi :", e)

        if not wlan.isconnected():
            print("WiFi echoue, nouvel essai dans 5s...")
            time.sleep(5)
            try:
                wlan.deinit()
                wlan.init(mode=WLAN.STA)
            except Exception:
                pass

    print("WiFi connecte :", wlan.ifconfig()[0])
    return wlan


def connect_mqtt():
    """Cree et connecte un client MQTT, avec reessai."""
    while True:
        try:
            client = MQTTClient(CLIENT_ID, MQTT_BROKER, port=MQTT_PORT)
            client.connect()
            print("MQTT connecte !")
            return client
        except Exception as e:
            print("Erreur MQTT :", e, "- nouvel essai dans 5s")
            time.sleep(5)


def publish_mqtt(client, topic, payload):
    """Publie un message ; en cas d'echec, reconnecte et renvoie le nouveau client."""
    try:
        client.publish(topic.encode('utf-8'), payload.encode('utf-8'))
        print("Publie :", payload)
        led(LED_GREEN)
        return client
    except Exception as e:
        print("Erreur publication MQTT :", e)
        print("Tentative de reconnexion au broker...")
        led(LED_RED)
        return connect_mqtt()


def run_wifi(gps):
    led(LED_BLUE)
    wlan = connect_wifi()
    client = connect_mqtt()

    while True:
        if not wlan.isconnected():
            print("WiFi perdu, reconnexion...")
            led(LED_BLUE)
            wlan = connect_wifi()
            client = connect_mqtt()

        try:
            lat, lon = get_position(gps)
            if lat is not None:
                payload = '{{"lat":{},"lon":{}}}'.format(lat, lon)
                client = publish_mqtt(client, MQTT_TOPIC, payload)
        except Exception as e:
            print("Erreur inattendue dans la boucle :", e)
            led(LED_RED)

        time.sleep(WIFI_INTERVAL)


# =====================================================================
# MODE LORAWAN OTAA
# =====================================================================

def encode_position(lat, lon):
    """Encode lat/lon sur 3 octets chacune (6 octets au total).
    lat : -90..+90   -> 0..16777215  (precision ~1,2 m)
    lon : -180..+180 -> 0..16777215  (precision ~2,4 m)
    Le decodeur TTN doit faire l'operation inverse."""
    lat_i = int((lat + 90.0) / 180.0 * 16777215)
    lon_i = int((lon + 180.0) / 360.0 * 16777215)
    return bytes([
        (lat_i >> 16) & 0xFF, (lat_i >> 8) & 0xFF, lat_i & 0xFF,
        (lon_i >> 16) & 0xFF, (lon_i >> 8) & 0xFF, lon_i & 0xFF,
    ])


def join_lora():
    """Rejoint le reseau LoRaWAN en OTAA et renvoie (lora, socket)."""
    lora = LoRa(mode=LoRa.LORAWAN, region=LoRa.EU868)
    print("MAC LoRa du FiPy (DevEUI par defaut) :",
          ubinascii.hexlify(lora.mac()).upper().decode())

    dev_eui = ubinascii.unhexlify(DEV_EUI)
    app_eui = ubinascii.unhexlify(APP_EUI)
    app_key = ubinascii.unhexlify(APP_KEY)

    led(LED_BLUE)
    lora.join(activation=LoRa.OTAA, auth=(dev_eui, app_eui, app_key), timeout=0)

    while not lora.has_joined():
        time.sleep(2.5)
        print("Not yet joined...")
    print("Joined")

    s = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
    s.setsockopt(socket.SOL_LORA, socket.SO_DR, LORA_DR)
    s.bind(LORA_PORT)
    return lora, s


def send_lora(s, data):
    """Envoie un uplink puis lit un eventuel downlink (fenetres RX1/RX2)."""
    s.setblocking(True)          # attend la fin de l'emission et des fenetres RX
    s.send(data)
    print("Uplink envoye :", ubinascii.hexlify(data).decode())
    led(LED_GREEN)

    s.setblocking(False)         # sinon recv() bloque s'il n'y a pas de downlink
    downlink = s.recv(64)
    if downlink:
        print("Downlink recu :", ubinascii.hexlify(downlink).decode())
    return downlink


def run_lora(gps):
    lora, s = join_lora()

    while True:
        try:
            lat, lon = get_position(gps)
            if lat is not None:
                payload = encode_position(lat, lon)
                print("Position :", lat, lon)
                send_lora(s, payload)
        except Exception as e:
            print("Erreur inattendue dans la boucle :", e)
            led(LED_RED)

        # Obligatoire : duty cycle 1 % en EU868 + Fair Use Policy TTN
        time.sleep(LORA_INTERVAL)


# =====================================================================
# PROGRAMME PRINCIPAL
# =====================================================================

pycom.heartbeat(False)
print("Demarrage du tracker en mode", MODE)

py = Pycoproc()
time.sleep(1)
gps = L76GNSS(pytrack=py, timeout=30)
print("GNSS initialise.")

if MODE == "LORA":
    run_lora(gps)
else:
    run_wifi(gps)