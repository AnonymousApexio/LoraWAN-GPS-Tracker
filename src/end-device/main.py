import time
import pycom
import socket
import machine
import ubinascii
import config
from machine import Pin
from network import WLAN, LoRa
from lib.mqtt import MQTTClient
from lib.pycoproc_2 import Pycoproc
from lib.L76GNSS import L76GNSS
from lib.LIS2HH12 import LIS2HH12
import lib.requests as requests

time.sleep(3) 

print("=== TRACKER SAE501 - VERSION 5 (LoRa + STOP + reveil accelerometre) ===")

# =====================================================================
# CONFIGURATION
# =====================================================================

# Mode de transmission :
#   "WIFI" -> Validation 1 : WiFi + MQTT direct vers le broker
#   "LORA" -> Validations 2 et suivantes : LoRaWAN OTAA vers TTN
MODE = "LORA"

# --- WiFi / MQTT (mode "WIFI") ---
WIFI_SSID = config.WIFI_SSID
WIFI_PASS = config.WIFI_PASS
MQTT_BROKER = config.MQTT_BROKER
MQTT_PORT = 1883
MQTT_TOPIC = config.MQTT_TOPIC
# Identifiant unique, derive du numero de serie de la carte (evite l'erreur MQTT 104)
CLIENT_ID = config.CLIENT_ID + ubinascii.hexlify(machine.unique_id()).decode()
WIFI_INTERVAL = config.WIFI_INTERVAL # secondes entre deux publications MQTT
PUSHBULLET_TOKEN = config.PUSHBULLET_TOKEN

# --- LoRaWAN OTAA (mode "LORA") ---
# Valeurs copiees depuis la page du device sur TTN, format hex MSB, sans espaces.
# NE PAS pousser ces cles sur un depot GitHub public.
DEV_EUI = config.DEV_EUI                  # DevEUI  (MAC LoRa du FiPy)
APP_EUI = config.APP_EUI                 # JoinEUI
APP_KEY = config.APP_KEY  # AppKey  (32 caracteres hex)
LORA_PORT = 1            # FPort des uplinks
LORA_DR = 5              # DR5 = SF7 en EU868 (le plus court en temps d'antenne)
LORA_INTERVAL = 150      # secondes entre deux uplinks (voir Fair Use Policy TTN)

# --- Ordre STOP recu par downlink (Validation 7) ---
CMD_STOP = 0x01          # octet produit par le downlink formatter TTN pour {"commande": "stop"}

# --- Veille et reveil par l'accelerometre (Validation 6, etape 9) ---
SEUIL_MOUVEMENT_MG = 300   # sensibilite du detecteur de mouvement, en mg (a ajuster aux tests)
DUREE_MOUVEMENT_MS = 200   # duree minimale du mouvement pour etre pris en compte
TEMPS_INACTIVITE = 600    # secondes sans mouvement avant la mise en veille
REVEIL_SECOURS = 300      # reveil automatique de secours si rien ne bouge (secondes)

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
    print("Pas encore de fix GPS...")
    led(LED_ORANGE)
    return None, None


# =====================================================================
# DETECTION DE MOUVEMENT ET VEILLE (Validation 6)
# =====================================================================

dernier_mouvement = time.time()


def sur_mouvement(pin):
    """Appelee automatiquement par l'accelerometre (interruption sur la broche P13).
    Broche a l'etat haut = activite detectee : on note l'heure du mouvement."""
    global dernier_mouvement
    if pin():
        dernier_mouvement = time.time()


def vehicule_immobile():
    """Vrai si aucun mouvement n'a ete detecte depuis TEMPS_INACTIVITE secondes."""
    return time.time() - dernier_mouvement > TEMPS_INACTIVITE


def entrer_en_veille(raison):
    """Met la carte en veille profonde ; elle se reveille au prochain mouvement
    (accelerometre) ou, a defaut, au bout de REVEIL_SECOURS secondes.
    Au reveil, main.py redemarre depuis le debut."""
    print("Mise en veille :", raison, "- secouer la carte pour la reveiller")
    led(LED_OFF)
    time.sleep(1)                                  # laisse partir les derniers print

    carte_pycom.setup_sleep(REVEIL_SECOURS)        # reveil de secours par le timer

    # Reveil du FiPy quand l'accelerometre leve la broche P13
    broche_reveil = [Pin('P13', mode=Pin.IN, pull=Pin.PULL_DOWN)]
    machine.pin_sleep_wakeup(broche_reveil, machine.WAKEUP_ANY_HIGH, True)

    # gps=True : le GPS garde sa memoire (fix plus rapide au reveil)
    # accelerometer_off=False : l'accelerometre reste actif pour pouvoir reveiller la carte
    carte_pycom.go_to_sleep(gps=True, pycom_module_off=False, accelerometer_off=False, wake_interrupt=True)
    machine.deepsleep(REVEIL_SECOURS * 1000)


def attendre(secondes):
    """Attend par pas d'une seconde, en surveillant l'inactivite pendant l'attente."""
    for _ in range(secondes):
        if vehicule_immobile():
            entrer_en_veille("vehicule immobile depuis " + str(TEMPS_INACTIVITE) + " s")
        time.sleep(1)


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
    
def verifier_ordre_pushbullet():
    """Interroge Pushbullet pour lire le dernier push. Supprime le push si c'est un ordre STOP."""
    try:
        en_tetes = {"Access-Token": PUSHBULLET_TOKEN}
        url_get = "https://api.pushbullet.com/v2/pushes?active=true&limit=1"
        
        reponse = requests.get(url_get, headers=en_tetes)
        donnees = reponse.json()
        reponse.close()

        pushes = donnees.get("pushes", [])
        if len(pushes) > 0:
            dernier_message = pushes[0]
            corps = dernier_message.get("body", "").strip().lower()
            
            if corps == "stop":
                iden = dernier_message.get("iden")
                print("Ordre STOP détecté ! Suppression du message sur Pushbullet...")
                
                # Suppression du message
                if iden:
                    url_delete = "https://api.pushbullet.com/v2/pushes/" + iden
                    reponse_del = requests.request("DELETE", url_delete, headers=en_tetes)
                    reponse_del.close()
                
                return True
                
    except Exception as e:
        print("Erreur de connexion a l'API Pushbullet :", e)
        
    return False

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

            if verifier_ordre_pushbullet():
                entrer_en_veille("ordre STOP recu depuis Pushbullet (WiFi)")

        except Exception as e:
            print("Erreur inattendue dans la boucle :", e)
            led(LED_RED)

        attendre(WIFI_INTERVAL)


# =====================================================================
# MODE LORAWAN OTAA
# =====================================================================

def encode_position(lat, lon):
    """Validation 5 : encode lat/lon sur 3 octets chacune (6 octets au total).
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
                downlink = send_lora(s, payload)

                # Validation 7 : un downlink ne peut arriver que juste apres
                # un uplink (Classe A, fenetres RX1/RX2).
                if downlink and downlink[0] == CMD_STOP:
                    entrer_en_veille("ordre STOP recu depuis la passerelle LoRa (TTN)")
        except Exception as e:
            print("Erreur inattendue dans la boucle :", e)
            led(LED_RED)

        # Obligatoire : duty cycle 1 % en EU868 + Fair Use Policy TTN.
        # L'attente surveille aussi l'inactivite du vehicule.
        attendre(LORA_INTERVAL)


# =====================================================================
# PROGRAMME PRINCIPAL
# =====================================================================

pycom.heartbeat(False)
print("Demarrage du tracker en mode", MODE)

try:
    print("Raison du demarrage :", machine.wake_reason())
except Exception:
    pass

carte_pycom = Pycoproc()
time.sleep(1)
gps = L76GNSS(pytrack=carte_pycom, timeout=30)

# Parametre "pysense" : c'est le nom attendu par la librairie, valable aussi pour la Pytrack
accelerometre = LIS2HH12(pysense=carte_pycom)
accelerometre.enable_activity_interrupt(SEUIL_MOUVEMENT_MG, DUREE_MOUVEMENT_MS, sur_mouvement)
dernier_mouvement = time.time()
print("GNSS et accelerometre initialises.")

led(LED_GREEN)
time.sleep(1)
led(LED_OFF)

if MODE == "LORA":
    run_lora(gps)
else:
    run_wifi(gps)