# Flexom 2.0 / BuildingCare pour Home Assistant

Intégration custom (HACS) pour les logements connectés **Flexom 2.0** de Bouygues
Immobilier, motorisés par la plateforme **Hemis** d'Ubiant. Depuis octobre 2026
l'app mobile s'appelle **BuildingCare** (éditeur U2P / OpenCaps) : l'API est la
même, tes identifiants sont les mêmes.

Contrairement à l'intégration native « Bouygues Flexom » (Overkiz), qui ne couvre
que Flexom v1, celle-ci parle directement à l'API Hemis de ton logement.

## Ce que ça expose

| Plateforme | Source Hemis | Détail |
|---|---|---|
| `light` | facteur `BRI` par zone | on/off (relais) |
| `cover` | facteur `BRIEXT` par zone | position 0-100 %, ouvrir / fermer / stop |
| `climate` | facteur `TMP` par zone | consigne + température mesurée si la zone a un capteur |
| `binary_sensor` | capteur `SMOKE` | détecteur de fumée (Nexelec Insafe+) |
| `sensor` | capteurs des objets | température, humidité, qualité d'air, confort, batterie, index électrique / chauffage / eau chaude (compteurs EWATTCH, compatibles tableau de bord Énergie) |
| `event` | capteur `SWS` | appuis sur les interrupteurs muraux (EnOcean VIMAR) |

Chaque zone × facteur est un appareil HA (« Chambre 1 Volet », « Séjour Lumière »).
Chaque objet physique porteur de capteurs (détecteur, compteur, interrupteur) est
aussi un appareil HA avec ses entités.

### Temps réel

Les changements d'état arrivent par **WebSocket STOMP** depuis le serveur Hemis
(action depuis l'app, interrupteur mural, fin de course d'un volet) en moins
d'une seconde. Un polling toutes les 30 s sert de filet de sécurité : 3 appels
REST au total (réglages de toutes les zones, tous les capteurs, infos système).

### Interrupteurs muraux comme déclencheurs

Chaque appui sur un interrupteur physique :

- met à jour l'entité `event.<interrupteur>`, utilisable directement comme déclencheur
  d'automatisation. Le type d'événement est la **position** de la touche pressée :
  `top` / `bottom` pour un interrupteur simple, `top_left` / `bottom_left` /
  `top_right` / `bottom_right` pour un double, plus `released`. Selon le câblage,
  « haut » peut allumer ou éteindre : c'est la position physique, pas la fonction ;
- émet un événement `flexom2_switch_pressed` sur le bus HA avec `sensor_id`,
  `thing_id`, `name`, `zone`, `value`, `timestamp`.

## Installation

1. HACS → Intégrations → menu ⋮ → *Dépôts personnalisés* → ajouter
   `https://github.com/LGDOFM/home-assistant-flexom2` (catégorie *Integration*).
2. Installer « Flexom 2.0 / BuildingCare », redémarrer Home Assistant.
3. Paramètres → Appareils et services → Ajouter une intégration → *Flexom 2.0*.
4. Renseigner l'email et le mot de passe de l'app mobile.

Installation manuelle : copier `custom_components/flexom2` dans le dossier
`custom_components` de ta configuration HA.

## Architecture

```
Ubiant Hemisphere (compte, liste des bâtiments)
        │  POST /users/signin  →  JWT
        ▼
Hemis du bâtiment  {hemis_base_url}/hemis/rest   (REST, 1 instance par logement)
        │  /WS_ReactiveEnvironmentDataManagement/settings   réglages de toutes les zones
        │  /intelligent-things/sensors                      tous les capteurs
        │  /intelligent-things/listV2                       objets, zones, types
        │  PUT .../{zone}/settings/{factor}/value           commandes
        ▼
Hemis STOMP  {hemis_stomp_url}  topic jms.topic.{buildingId}.data   (push temps réel)
```

Le client Python (`custom_components/flexom2/flexom_client`) est embarqué, sans
dépendance externe à installer. Le serveur Hemis publie sa propre spec OpenAPI sur
`{hemis_base_url}/swagger.json` si tu veux aller plus loin.

## Limites connues

- Pas de variateur : les lumières Flexom sont des relais on/off.
- Le mode chauffage est toujours « heat » (Hemis n'expose pas de mode via le facteur TMP).
- Les objets en état `MUTE` côté Hemis (ex. thermostat Somfy jamais appairé) sont ignorés.
- Un nouvel objet ajouté dans l'installation apparaît après un rechargement de l'intégration.

## Développement

Le code source du client et les notes de reverse engineering de l'API vivent dans
le dépôt de travail (`flexom-client-py/`, `research/`). Le client y est développé
puis copié tel quel dans `custom_components/flexom2/flexom_client/`.

### Tests

`tests/test_live_building.py` monte l'intégration dans un vrai cœur Home Assistant
(via `pytest-homeassistant-custom-component`) contre ton bâtiment, en lecture seule :
aucune commande n'est envoyée aux équipements. Il vérifie les entités créées, les
noms, les appareils, puis rejoue des événements STOMP.

```
pip install homeassistant pytest-homeassistant-custom-component
FLEXOM_EMAIL=... FLEXOM_PASSWORD=... pytest
```

Sans identifiants, le test est ignoré. Sous Windows, `tests/conftest.py` neutralise
le blocage réseau du plugin HA et force une boucle asyncio compatible avec aiodns.

Licence MIT.
