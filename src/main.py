import time
import pycom
from network import WLAN
from lib.mqtt import MQTTClient
from lib.pycoproc_2 import Pycoproc
from lib.L76GNSS import L76GNSS

# --- Configuration ---
WIFI_SSID = "Anonymous"
WIFI_PASS = "123456789motdepasse"
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
MQTT_TOPIC = "sae501/vehicule/pos"
CLIENT_ID = "pycom-sae501"

# --- Fonctions utilitaires ---
def connect_wifi():
    """Se connecte au WiFi avec réessai automatique."""
    wlan = WLAN(mode=WLAN.STA)

    while not wlan.isconnected():
        try:
            print("Tentative de connexion WiFi...")
            wlan.connect(WIFI_SSID, auth=(WLAN.WPA2, WIFI_PASS), timeout=10000)
            # Attend jusqu'à 10 secondes
            for _ in range(20):
                if wlan.isconnected():
                    break
                time.sleep(0.5)
        except Exception as e:
            print("Erreur WiFi :", e)

        if not wlan.isconnected():
            print("WiFi échoué, nouvel essai dans 5s...")
            time.sleep(5)
            try:
                wlan.deinit()
                wlan.init(mode=WLAN.STA)
            except:
                pass

    print("WiFi connecté :", wlan.ifconfig()[0])
    return wlan


def connect_mqtt():
    """Crée et connecte un client MQTT, avec réessai."""
    while True:
        try:
            client = MQTTClient(CLIENT_ID, MQTT_BROKER, port=MQTT_PORT)
            client.connect()
            print("MQTT connecté !")
            return client
        except Exception as e:
            print("Erreur MQTT :", e, "- nouvel essai dans 5s")
            time.sleep(5)


def read_gps(gps):
    """Lit les coordonnées GPS avec gestion d'erreur.
    Retourne (lat, lon) ou (None, None)."""
    try:
        coord = gps.coordinates(debug=False)
        if coord is not None and coord != (None, None):
            lon, lat = coord
            if lat is not None and lon is not None:
                return lat, lon
    except Exception as e:
        print("Erreur GPS :", e)
    return None, None


# --- Programme principal ---
print("Démarrage du tracker...")

# 1. WiFi
wlan = connect_wifi()

# 2. Pytrack 2.0
py = Pycoproc()
time.sleep(1)

# 3. GNSS
gps = L76GNSS(pytrack=py, timeout=30)
print("GNSS initialisé.")

# 4. MQTT
client = connect_mqtt()

# 5. Boucle principale avec réessai automatique
while True:
    if not wlan.isconnected():
        print("WiFi perdu, reconnexion...")
        wlan = connect_wifi()
        client = connect_mqtt()

    try:
        lat, lon = read_gps(gps)

        if lat is not None and lon is not None:
            payload = '{{"lat":{},"lon":{}}}'.format(lat, lon)

            try:
                client.publish(MQTT_TOPIC, payload)
                print("Publié :", payload)
            except Exception as e:
                print("Erreur publication MQTT :", e)
                client = connect_mqtt()
        else:
            print("Pas encore de fix GPS...")

    except Exception as e:
        print("Erreur inattendue dans la boucle :", e)

    time.sleep(5)