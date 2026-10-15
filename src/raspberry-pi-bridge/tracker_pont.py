import json
import math
import time

import requests
import paho.mqtt.client as mqtt
import config

# =====================================================================
# CONFIGURATION
# =====================================================================

PUSHBULLET_TOKEN = config.PUSHBULLET_TOKEN
TTN_APP_ID = config.TTN_APP_ID
TTN_DEV_ID = config.TTN_DEV_ID
TTN_API_KEY = config.TTN_API_KEY
TTN_BROKER = config.TTN_BROKER

INTERVALLE_PUSHBULLET = 15      # sec entre 2 lectures des ordres Pushbullet
SEUIL_DEPLACEMENT_M   = 15      # distance mini vs point de reference pour "bouge"
NB_CONFIRMATIONS      = 2       # nb d'uplinks consecutifs pour changer d'etat
RAPPEL_MOUVEMENT_S    = 300     # rappel periodique en mouvement (0 = off)
SEUIL_SILENCE_S       = 75     # silence > 400 s => tracker considere comme revenu

TOPIC = "v3/" + TTN_APP_ID + "@ttn/devices/" + TTN_DEV_ID
PB_URL = "https://api.pushbullet.com/v2/pushes"
PB_HEADERS = {"Access-Token": PUSHBULLET_TOKEN}

# =====================================================================
# ETAT GLOBAL
# =====================================================================

derniere_position     = None     # derniere position brute recue
position_reference    = None     # dernier point stable (pour mesurer le deplacement)
etat                  = "ARRETE" # "ARRETE" ou "EN_MOUVEMENT"
compteur_mouvement    = 0
compteur_arret        = 0
dernier_rappel        = 0
derniere_uplink_ts    = 0        # timestamp du dernier uplink (pour detecter le retour)

# =====================================================================
# PUSHBULLET
# =====================================================================

def notifier(titre, texte):
    try:
        r = requests.post(PB_URL, headers=PB_HEADERS, timeout=10,
                          json={"type": "note", "title": titre, "body": texte})
        if r.status_code != 200:
            print("Erreur Pushbullet :", r.status_code, r.text)
    except requests.RequestException as e:
        print("Pushbullet injoignable :", e)

def distance_m(p1, p2):
    lat1, lon1 = map(math.radians, p1)
    lat2, lon2 = map(math.radians, p2)
    a = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(a))

# =====================================================================
# TTN MQTT
# =====================================================================

def sur_connexion(client, userdata, flags, reason_code, properties):
    print("Connecte a TTN :", reason_code)
    client.subscribe(TOPIC + "/up")
    client.subscribe(TOPIC + "/down/sent")

def sur_message(client, userdata, msg):
    global derniere_position, position_reference, etat
    global compteur_mouvement, compteur_arret, dernier_rappel, derniere_uplink_ts

    # --- Confirmation que TTN a transmis un downlink ---
    if msg.topic.endswith("/down/sent"):
        notifier("Tracker en veille", "Ordre de veille transmis au tracker.")
        return

    # --- Uplink de position ---
    try:
        pos = json.loads(msg.payload)["uplink_message"]["decoded_payload"]
        position = (pos["lat"], pos["lon"])
    except (ValueError, KeyError):
        print("Uplink ignore (pas de position decodee)")
        return

    maintenant = time.time()

    # --- Detection "retour en ligne" apres un long silence ---
    if derniere_uplink_ts > 0 and (maintenant - derniere_uplink_ts) > SEUIL_SILENCE_S:
        print(">>> Retour en ligne apres {:.0f} s de silence".format(
            maintenant - derniere_uplink_ts))
        notifier(
            "Tracker de retour en ligne",
            "Position : {:.5f}, {:.5f}\nhttps://maps.google.com/?q={},{}".format(
                position[0], position[1], position[0], position[1])
        )
        # On repart proprement : nouvelle reference, etat ARRETE
        position_reference = position
        etat = "ARRETE"
        compteur_mouvement = 0
        compteur_arret = 0

    derniere_uplink_ts = maintenant

    # --- Premiere position connue ---
    if position_reference is None:
        position_reference = position
        derniere_position = position
        print("Premiere position :", position)
        return

    # --- Distance depuis le dernier point STABLE (pas la position precedente) ---
    d = distance_m(position_reference, position)
    print("d = {:.1f} m | etat = {} | mvts = {} | arrets = {}".format(
        d, etat, compteur_mouvement, compteur_arret))

    if d > SEUIL_DEPLACEMENT_M:
        compteur_mouvement += 1
        compteur_arret = 0
    else:
        compteur_arret += 1
        compteur_mouvement = 0

    # --- ARRETE -> EN_MOUVEMENT ---
    if etat == "ARRETE" and compteur_mouvement >= NB_CONFIRMATIONS:
        etat = "EN_MOUVEMENT"
        position_reference = position   # nouveau point de depart
        dernier_rappel = maintenant
        notifier(
            "ALERTE : le vehicule se deplace",
            "Deplacement de {:.0f} m depuis le dernier point stable\n"
            "https://maps.google.com/?q={},{}".format(d, position[0], position[1])
        )
        print(">>> Passage en MOUVEMENT")

    # --- EN_MOUVEMENT -> ARRETE ---
    elif etat == "EN_MOUVEMENT" and compteur_arret >= NB_CONFIRMATIONS:
        etat = "ARRETE"
        position_reference = position   # on fige le point d'arret
        notifier(
            "Vehicule arrete",
            "Le vehicule ne bouge plus.\n"
            "https://maps.google.com/?q={},{}".format(position[0], position[1])
        )
        print(">>> Retour a l'ARRET")

    # --- Rappel periodique en mouvement ---
    elif etat == "EN_MOUVEMENT" and RAPPEL_MOUVEMENT_S > 0:
        if maintenant - dernier_rappel >= RAPPEL_MOUVEMENT_S:
            dernier_rappel = maintenant
            notifier(
                "Vehicule toujours en mouvement",
                "https://maps.google.com/?q={},{}".format(position[0], position[1])
            )

    derniere_position = position

# =====================================================================
# ORDRE DE VEILLE
# =====================================================================

def envoyer_ordre_veille(client):
    global etat, position_reference, compteur_mouvement, compteur_arret
    ordre = {"downlinks": [{"f_port": 1,
                            "decoded_payload": {"commande": "stop"},
                            "priority": "NORMAL"}]}
    client.publish(TOPIC + "/down/replace", json.dumps(ordre))
    print("Ordre de veille publie sur TTN")
    # On remet l'etat a zero : au reveil, la 1ere position servira de reference
    etat = "ARRETE"
    position_reference = None
    compteur_mouvement = 0
    compteur_arret = 0

# =====================================================================
# LECTURE DES ORDRES PUSHBULLET
# =====================================================================

def verifier_commandes(client, depuis):
    r = requests.get(PB_URL, headers=PB_HEADERS, timeout=10,
                     params={"active": "true", "modified_after": depuis})
    r.raise_for_status()
    pushes = r.json().get("pushes", [])

    for push in pushes:
        if push.get("type") == "note" and (push.get("body") or "").strip().lower() == "stop":
            print("STOP recu depuis Pushbullet")
            envoyer_ordre_veille(client)

    return max([p["modified"] for p in pushes], default=depuis)

# =====================================================================
# PROGRAMME PRINCIPAL
# =====================================================================

if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(TTN_APP_ID + "@ttn", TTN_API_KEY)
    client.tls_set()
    client.on_connect = sur_connexion
    client.on_message = sur_message
    client.connect(TTN_BROKER, 8883)
    client.loop_start()

    depuis = time.time()
    print("Pont Pushbullet <-> TTN demarre")
    while True:
        try:
            depuis = verifier_commandes(client, depuis)
        except (requests.RequestException, ValueError) as e:
            print("Erreur Pushbullet :", e)
        time.sleep(INTERVALLE_PUSHBULLET)
