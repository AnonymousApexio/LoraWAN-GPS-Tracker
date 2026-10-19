# Traçage de véhicule par GNSS sur réseau LoRaWAN privé

> SAE 5.01 – BUT Réseaux & Télécommunications
> Déploiement d'un LNS ChirpStack auto-hébergé en remplacement de The Things Network.

---

## 📋 Description

Ce projet consiste à suivre la position GNSS d'un véhicule en transmettant ses coordonnées via un réseau **LoRaWAN** privé, puis à les visualiser sur une carte web. L'objectif final est un système embarqué à faible consommation : le tracker ne s'active que lorsque le véhicule bouge (détection par accéléromètre) et peut être mis en veille à distance par un ordre descendant (downlink).

Le projet est initialement basé sur **The Things Network (TTN)**. Cette version utilise un **LoraWAN Network Server (LNS) auto-hébergé** : [ChirpStack v4](https://www.chirpstack.io/) déployé sur un Raspberry Pi.

---

## 🏗️ Architecture

![Image architecture](image.png)
- Image généré par IA
---

## 🧰 Matériel requis

| Composant | Rôle |
|---|---|
| FiPy ou LoPy + Pytrack | End-Device (tracker GNSS embarqué) |
| FiPy ou LoPy + Expansion 3 / Pysense | Nano-Gateway LoRaWAN monocanal |
| 2 antennes LoRa | Une par module |
| Raspberry Pi (Trixie) | Serveur LNS + Node-RED |
| Au minimum un AP / smartphone en mode partage de connexion | Réseaux Wi-Fi |

> ⚠️ **Redis ≥ 6.2 est obligatoire** pour ChirpStack. Raspberry Pi OS **Bookworm** fournit Redis 7. Vérifier avec `cat /etc/os-release`.

---

## 💻 Logiciels

- **ChirpStack v4** (paquets Debian officiels)
- **ChirpStack Gateway Bridge**
- **Mosquitto**
- **PostgreSQL 13+** avec extension `pg_trgm`
- **Redis 6.2+**
- **Node-RED** (dashboard + carte)
- **Python 3** avec `paho-mqtt` et `requests` (script Pushbullet)
- **Pycom firmware** + Pymakr (VS Code / Atom)

---

## ⚒️ Architecture du projet

```
/
└── .dist/
└── assets/                 # Dossier des images pour le README
    ├── ...
└── src/                    # Dossier du code source
    └── end-device/         # Dossier du tracker embarqué
        └── lib/            # Dossier des libraries Pycom
            ├── L76GNSS.py
            ├── LIS2HH12.py
            ├── mqtt.py
            ├── pycoproc_1.py
            ├── pycoproc_2.py
        ├── boot.py
        ├── config.py       # Configuration du tracker (clé AppKey, WiFi, etc.)
        ├── main.py         # Code principal du tracker (boucle principale, accéléromètre, GNSS, LoRaWAN)
    └── gateway/            # Dossier de la nano-passerelle LoRaWAN
        ├── boot.py
        ├── config.py       # Configuration de la passerelle (IP du serveur, WiFi, fréquence LoRa, etc.)
        ├── main.py         # Code principal de la passerelle (boucle principale, réception LoRa, envoi UDP)
        ├── nanogateway.py  # Code de la nano-passerelle (réception LoRa, envoi UDP)
    └── LNS/
        ├── uplink-formatter.js # Code JavaScript pour décoder les uplinks dans TheThingsNetwork (Au cas où vous voudriez basculer vers TTN)
        ├── downlink-formatter.js # Code JavaScript pour décoder les downlinks dans TheThingsNetwork (Au cas où vous voudriez basculer vers TTN)
    └── node-red/           # Dossier de configuration Node-RED
        ├── flows.json      # Configuration des flux Node-RED (carte, fonctions, MQTT)
    └── raspberry-pi-bridge/
        ├── config.py       # Configuration du script Pushbullet (UUID de l'application, DevEUI, token Pushbullet)
        ├── tracker_pont.py # Script Python pour relayer les uplinks vers Pushbullet
    ├── pymakr.conf
└── README.md               # Documentation du projet
```

---

## 🚀 Installation

### 1. ChirpStack sur le Raspberry Pi

```bash
# Dépendances
sudo apt update
sudo apt install -y mosquitto mosquitto-clients redis-server redis-tools postgresql gpg

# Base PostgreSQL
sudo -u postgres psql
```

Création de l'utilisateur et de la base ChirpStack (remplacer `VOTRE_MOT_DE_PASSE`) :
```sql
CREATE ROLE chirpstack WITH LOGIN PASSWORD 'VOTRE_MOT_DE_PASSE';
CREATE DATABASE chirpstack WITH OWNER chirpstack;
\c chirpstack
CREATE EXTENSION pg_trgm;
\q
```

```bash
# Dépôt ChirpStack 4.x
sudo mkdir -p /etc/apt/keyrings/
sudo sh -c 'wget -q -O - https://artifacts.chirpstack.io/packages/chirpstack.key | gpg --dearmor > /etc/apt/keyrings/chirpstack.gpg'
echo "deb [signed-by=/etc/apt/keyrings/chirpstack.gpg] https://artifacts.chirpstack.io/packages/4.x/deb stable main" | sudo tee /etc/apt/sources.list.d/chirpstack.list
sudo apt update

# Gateway Bridge
sudo apt install -y chirpstack-gateway-bridge
sudo systemctl enable --now chirpstack-gateway-bridge

# ChirpStack
sudo apt install -y chirpstack
```

### 2. Configuration du Gateway Bridge

Fichier `/etc/chirpstack-gateway-bridge/chirpstack-gateway-bridge.toml` :

```toml
[integration.mqtt]
event_topic_template="eu868/gateway/{{ .GatewayID }}/event/{{ .EventType }}"
state_topic_template="eu868/gateway/{{ .GatewayID }}/state/{{ .StateType }}"
command_topic_template="eu868/gateway/{{ .GatewayID }}/command/#"
```
La raison de ce préfixe `eu868` est que la nano-passerelle Pycom n'annonce qu'une seule région (`eu868`) et un seul canal (868,1 MHz). ChirpStack Gateway Bridge publie donc les événements sur le topic MQTT `eu868/gateway/...`.

```bash
sudo systemctl restart chirpstack-gateway-bridge
```

### 3. Configuration de ChirpStack

```bash
openssl_rand_-base64_32
```

Utilisez le résultat pour le paramètre `secret` dans le fichier de configuration ci-dessous. 

Fichier `/etc/chirpstack/chirpstack.toml` :

```toml
[postgresql]
dsn="postgres://chirpstack:VOTRE_MOT_DE_PASSE@localhost/chirpstack?sslmode=disable" # Remplacer VOTRE_MOT_DE_PASSE par le mot de passe choisi pour l'utilisateur chirpstack

[network]
enabled_regions=["eu868"]

[api]
bind="0.0.0.0:8080"
secret="RESULTAT_DE_openssl_rand_-base64_32"

[integration]
enabled=["mqtt"]

[integration.mqtt]
server="tcp://localhost:1883/"
json=true
```

Générer le secret : `openssl rand -base64 32`

### 4. Configuration du réseau EU868 (monocanal)

Fichier `/etc/chirpstack/region_eu868.toml`, dans `[regions.network]` :

```toml
adr_disabled=true
# Mettre en commentaire les 5 blocs [[regions.network.extra_channels]]
```

> **Pourquoi ?** La nano-passerelle Pycom n'écoute qu'une seule fréquence (868,1 MHz) et un seul SF (SF7). Sans ces ajustements, ChirpStack demanderait au FiPy de changer de canal/SF et la communication échouerait.

Redémarrer :
```bash
sudo systemctl restart chirpstack
sudo journalctl -f -n 50 -u chirpstack
```

L'interface web répond sur `http://172.20.10.6:8080` (admin / admin (Par défaut) à changer immédiatement).

### 5. Mosquitto - écoute sur toutes les interfaces

Créer `/etc/mosquitto/conf.d/listener.conf` :

```
listener 1883 0.0.0.0
allow_anonymous true
```

Vous pouvez modifier le port pour 8883 si vous souhaitez utilisez MQTT sur TLS ou ajouter un mot de passe si vous le souhaitez. Redémarrer Mosquitto :

```bash
sudo systemctl restart mosquitto
sudo ss -tlnp | grep 1883   # doit afficher 0.0.0.0:1883
```

---

## 📡 Nano-Gateway Pycom

(Pour comprenre) Récupérez les fichiers depuis [pycom/pycom-libraries](https://github.com/pycom/pycom-libraries) -> `examples/lorawan-nano-gateway/` pour l'exemple.

Sinon: 

**`gateway/config.py` (passerelle) :**

```python
SERVER = '<SERVER_IP/HOSTNAME>'      # IP du Raspberry
PORT = 1700 # Port par défaut pour le protocole Semtech UDP
WIFI_SSID = '...'
WIFI_PASS = '...'
LORA_FREQUENCY = 868100000  # 868,1 MHz
LORA_GW_DR = "SF7BW125"
LORA_NODE_DR = 5 # DR5 = SF7 en EU868
```

Au démarrage, la console affiche le **Gateway ID** (16 caractères hex avec `FFFE` au milieu). Le noter pour la déclaration de la gateway dans ChirpStack.

**Vérification :** la console doit afficher des lignes `Pull ack` toutes les 25 s.

> ⚠️ **Ne jamais alimenter un module sans son antenne LoRa** (risque de destruction de l'étage radio). Garder 2–3 m entre gateway et tracker.

---

## 🔑 Déclaration dans ChirpStack

Dans l'interface web, créer dans l'ordre :

1. **Gateways** -> Add gateway
   - Gateway ID = identifiant de la nano-passerelle
   ![Gateway](assets/gateway.png)
   - Intervalle de statistiques : 30 s

2. **Device profiles** -> Add device profile
   - Nom : `NOM_VOTRE_DEVICE`
   - Region : EU868 | MAC version : LoRaWAN 1.0.3 | Regional parameters revision : A (Si vous utilisez un FiPy)
   - Expected uplink interval : 15 s (Si vous modifiez `LORA_INTERVAL` dans le code du end-device, mettre la même valeur ici)
   - Cocher **Device supports OTAA**
   ![device_profile](assets/device_profile.png)
   - **Codec** JavaScript :
    
```javascript
function decodeUplink(input) {
  var b = input.bytes;
  if (b.length !== 6) {
    return { errors: ["6 octets attendus, " + b.length + " recus"] };
  }
  var latRaw = (b[0] << 16) | (b[1] << 8) | b[2];
  var lonRaw = (b[3] << 16) | (b[4] << 8) | b[5];
  return {
    data: {
      lat: Math.round((latRaw / 16777215 * 180 - 90) * 1e6) / 1e6,
      lon: Math.round((lonRaw / 16777215 * 360 - 180) * 1e6) / 1e6
    }
  };
}

function encodeDownlink(input) {
  if (input.data && input.data.commande === "stop") {
    return { bytes: [0x01] };
  }
  return { errors: ["commande inconnue"] };
}
```
![codec](assets/codec.png)


3. **Applications** --> Add application (nom : `VOTRE_APPLICATION`)
   - Noter l'**UUID** de l'application --> utilisé dans les topics MQTT
    ![application](assets/application.png)
4. Dans l'application --> **Add device**
   - Device EUI, Join EUI (0000000000000000), profil `NOM_VOTRE_DEVICE`
   ![end device](assets/end_device.png)
   - Onglet **OTAA keys** : générer une nouvelle Application key
   ![OTAA](assets/OTAA.png)
---

## 🛰️ End-Device (tracker)

**`end-device/config.py` :** remplacer `APP_KEY` par la clé générée dans ChirpStack.

---

## 🔔 Node-RED

Basculer du broker TTN au Mosquitto local :

1. **Nouveau nœud broker LNS local** : `localhost:1883`, sans TLS
2. **mqtt in uplinks** : topic `application/+/device/+/event/up`, sortie JSON
3. **Fonction de décodage** : la position est dans `msg.payload.object` (et non `uplink_message.decoded_payload`)

```javascript
var o = msg.payload.object;
if (!o || o.lat === undefined) {
    node.warn("Uplink sans position decodee");
    return null;
}
msg.payload = { name: "vehicule", lat: o.lat, lon: o.lon, icon: "car", iconColor: "red" };
node.status({ fill: "green", shape: "dot", text: o.lat.toFixed(5) + ", " + o.lon.toFixed(5) });
return msg;
```

4. **Fonction ordre STOP** (avec anti-rebond 5 min) :

```javascript
var APP_ID = "UUID-DE-L-APPLICATION";
var DEV_EUI = "<VOTRE_DEV_EUI>";
msg.topic = "application/" + APP_ID + "/device/" + DEV_EUI + "/command/down";
msg.payload = {
    devEui: DEV_EUI,
    confirmed: false,
    fPort: 1,
    object: { commande: "stop" }
};
```

5. **Suivi des downlinks** : mqtt in sur `application/+/device/+/event/+`, filtrer sur `txack` et `log`.

> ⚠️ ChirpStack n'a **pas** d'équivalent `down/replace` par MQTT comme TTN. Chaque publication ajoute un downlink à la file. En cas de doute : page du device, onglet **Queue** -> **Flush queue**.
![Queue](assets/Queue.png)
---

## 🐍 Script Pushbullet (`tracker_pont.py`)

Remplacer la configuration par la configuration de votre application et du device dans ChirpStack :

```python
# Starting constants
APP_ID = "UUID-DE-L-APPLICATION"
DEV_EUI = "<VOTRE_DEV_EUI>"
TOPIC = "application/" + APP_ID + "/device/" + DEV_EUI

# L205:
client.connect("localhost", <Votre_port>)
```

---

## 🧪 Recette de validation

- [ ] `systemctl status chirpstack chirpstack-gateway-bridge mosquitto redis-server postgresql` -> tous `active (running)`
- [ ] Console nano-passerelle : lignes `Pull ack` régulières
- [ ] ChirpStack -> page Gateways : `Last seen` récent
- [ ] Device -> onglet **LoRaWAN frames** : `JoinRequest` puis `JoinAccept`
- [ ] Console tracker : `Joined`
- [ ] Device -> onglet **Events** : événement `up` avec `object: {lat, lon}`
- [ ] `mosquitto_sub -t 'application/#' -v` affiche le JSON de l'uplink
- [ ] Node-RED : la voiture bouge sur la carte, les coordonnées se mettent à jour
- [ ] Bouton STOP : `txack` dans le debug Node-RED, `Downlink recu : 01` sur le tracker, arrêt des uplinks
- [ ] Secouer le tracker après accéléromètre stop : nouveau join, reprise des uplinks
- [ ] Pushbullet : notifications de position, puis « Tracker en veille »

---

## 🛠️ Dépannage

| Symptôme | Cause probable | Correctif |
|---|---|---|
| ChirpStack ne démarre pas | Redis < 6.2, `pg_trgm` absent, secret non défini | `redis-server --version` ≥ 6.2, `journalctl -u chirpstack` |
| Passerelle jamais vue | `SERVER` faux, UDP 1700 bloqué, préfixe `eu868` absent | `journalctl -u chirpstack-gateway-bridge`, `mosquitto_sub -t 'eu868/#' -v` |
| `Not yet joined` en boucle | Tracker sur autre canal/SF que la passerelle | Vérifier `add_channel` et `dr=LORA_DR` |
| `JoinRequest` sans `JoinAccept` | AppKey ou DevEUI différents | Recopier la clé, onglet Events du device |
| Join OK puis plus rien | Canaux ajoutés par le réseau | `extra_channels` en commentaire, `adr_disabled=true` |
| `up` sans `object` | Codec manquant ou erreur dans `decodeUplink` | Onglet Codec du profil |
| Rien dans Node-RED | Mauvais topic ou `json=false` | `mosquitto_sub -t 'application/#' -v` |
| STOP en file, jamais `txack` | Downlink trop tardif pour la nano-passerelle | `rx1_delay=3` dans `region_eu868.toml`, redémarrer ChirpStack |
| `ConnectionRefusedError` sur 1883/8883 | Mosquitto n'écoute que sur `127.0.0.1` | Ajouter `listener 1883 0.0.0.0` dans `/etc/mosquitto/conf.d/` |

---

## ⚠️ Limites connues

- **Nano-passerelle monocanal** : une seule fréquence (868,1 MHz) et un seul SF (SF7). Non conforme à la spécification LoRaWAN complète. TTN déconseille ce type de passerelle en production.
- **Passerelle partagée entre 2 groupes** : la nano-gateway n'envoie qu'à un seul serveur (`SERVER`). Prévoir un LNS commun (une application par groupe) ou des créneaux d'utilisation.
- **Réseaux Wi-Fi séparés** : si le Raspberry et le tracker sont sur deux partages de connexion différents (deux téléphones), ils ne peuvent pas communiquer directement.

---

## 📚 Références

- [ChirpStack – Quickstart Debian / Ubuntu](https://www.chirpstack.io/docs/getting-started/debian-ubuntu.html)
- [ChirpStack – MQTT integration](https://www.chirpstack.io/docs/chirpstack/integrations/mqtt.html)
- [ChirpStack – Device profiles & codecs](https://www.chirpstack.io/docs/chirpstack/use/device-profiles.html)
- [pycom/pycom-libraries – lorawan-nano-gateway](https://github.com/pycom/pycom-libraries)
- [Pycom – otaa_node.py example](https://github.com/pycom/pycom-libraries/blob/master/examples/lorawan-nano-gateway/otaa_node.py)

---

---

## 📄 Licence

Le code Pycom de **gateway/nanogateway.py** et de **gateway/main.py** est dérivé de `pycom-libraries` (GPL v3 avec termes additionnels Pycom Licence v1.0). Voir les en-têtes des fichiers concernés.