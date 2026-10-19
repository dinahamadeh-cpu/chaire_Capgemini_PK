# Gestion de places de parking

Application web Django pour gérer des parkings, leurs places et les réservations de véhicules.

## Lancer le site

### Prérequis
- Python 3.12 ou plus
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### Première installation
```bash
git clone https://github.com/dinahamadeh-cpu/chaire_Capgemini_PK.git
cd chaire_Capgemini_PK
uv sync                                  # installe les dépendances
uv run python manage.py migrate          # crée la base de données
uv run python manage.py seed_data        # ajoute des données de test
```

### Démarrer le site
```bash
uv run python manage.py runserver
```
Puis ouvrir **http://127.0.0.1:8000/** dans le navigateur.

> Le site tourne uniquement sur votre ordinateur : chacun doit le lancer chez soi.
> La base de données (`db.sqlite3`) est locale et n'est pas partagée sur GitHub.

### Carte des parkings (facultatif)
Les cartes de `/parkings/` et des pages de détail utilisent Google Maps. Les coordonnées (latitude, longitude) des parkings se renseignent dans `/admin/`.

### Données de test (`seed_data`)

```bash
uv run python manage.py seed_data
```
Cette commande crée 4 parkings et 40 places, des véhicules actuellement stationnés, un historique de départs et environ 30 jours de réservations passées (pour l'analyse de l'affluence), ainsi que les comptes suivants :

| Identifiant | Mot de passe | Rôle  |
|-------------|--------------|-------|
| agent1      | agent1234    | Agent |
| agent2      | agent1234    | Agent |
| demo        | demo1234     | Usager |

Pour accéder à l'administration (`/admin/`), créer un compte administrateur :
```bash
uv run python manage.py createsuperuser
```

## Fonctionnalités

### Côté usager
- **Accueil** (`/`) : accès aux parkings, à la connexion et à l'inscription. Une fois connecté, l'usager accède à ses réservations, à ses moyens de paiement et peut se déconnecter. Liens vers l'espace agent, l'administration et l'accès professionnel.
- **Comptes usagers** : créer un compte (`/inscription/`), se connecter (`/connexion/`) et se déconnecter.
- **Liste des parkings** (`/parkings/`) : chaque parking avec son nombre de places libres (badge « presque complet » / « complet »), son tarif, sa durée maximale et ses horaires, et une carte Google Maps. Le bouton « Voir sur la carte » centre la carte sur le parking choisi.
- **Détail d'un parking** (`/parkings/<id>/`) : carte de localisation, places disponibles, tarif horaire, durée maximale et horaires. Chaque place a un bouton « Réserver ».
- **Réservation et paiement simulé** (`/parkings/<id>/places/<id>/reserver/`) : l'usager saisit sa plaque (format `AA-123-AA`) et le nombre d'heures, voit le montant calculé et paie avec un moyen de paiement simulé (nouvelle carte ou carte déjà enregistrée).
- **Moyens de paiement** (`/moyens-de-paiement/`) : enregistrer un moyen de paiement simulé. Les informations de carte ne sont jamais conservées.
- **Mes réservations** (`/mes-reservations/`) : consulter ses réservations, les annuler, confirmer son arrivée puis déclarer son départ.
- **Récapitulatif** (`/mes-reservations/<id>/`) : arrivée, départ, durée réservée, durée réelle (avec alerte en cas de dépassement) et montant payé.

### Côté agent
- **Accès professionnel** (`/acces-professionnel/`) : choix entre l'espace agent et l'administration.
- **Connexion agent** (`/agent/login/`) : réservée aux comptes du groupe « Agents ».
- **Tableau de bord agent** (`/agent/`) : accès aux outils de l'agent.
- **Vérification de plaque** (`/agent/plaque/`) : l'agent saisit une plaque, voit si le véhicule a une réservation en cours (et si l'arrivée a été confirmée) et peut clôturer le stationnement.
- **Occupation en temps réel** (`/agent/statistiques/`) : taux d'occupation global et par parking, liste des véhicules stationnés (place, plaque, arrivée, fin prévue) et historique des derniers mouvements (réservations, départs, annulations) avec les plaques.
- **Analyse de l'affluence** (`/agent/affluence/`) : sur 7, 30 ou 90 jours, pour un parking ou tous, le pic d'occupation et le nombre de réservations par jour, l'affluence par heure et par jour de la semaine (heure de pointe, jour le plus chargé).

### Administration
- **Administration** (`/admin/`) : ajouter, modifier ou supprimer des parkings (tarif, durée maximale, horaires, coordonnées GPS), des places et des réservations.

### Règles en place
- une plaque ne peut avoir qu'une seule réservation active à la fois ;
- une place devient automatiquement indisponible quand elle est réservée, et disponible quand la réservation se termine ;
- la réservation est impossible si le tarif du parking n'est pas renseigné ;
- les pages usagers demandent d'être connecté, et les pages agent sont réservées au groupe « Agents » (vérifié côté serveur).

## Lancer les tests
```bash
uv run python manage.py test
```
