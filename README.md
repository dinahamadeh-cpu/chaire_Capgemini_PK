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
La carte de `/parkings/` utilise Google Maps. Pour l'afficher, définir la variable d'environnement `GOOGLE_MAPS_API_KEY` avant de lancer le serveur. Les coordonnées (latitude, longitude) des parkings se renseignent dans `/admin/`.

### Comptes de test (créés par `seed_data`)
| Identifiant | Mot de passe | Rôle  |
|-------------|--------------|-------|
| agent1      | agent1234    | Agent |
| agent2      | agent1234    | Agent |

Pour accéder à l'administration (`/admin/`), créer un compte administrateur :
```bash
uv run python manage.py createsuperuser
```

## Fonctionnalités

- **Accueil** (`/`) : accès aux parkings, à la connexion, à l'inscription, à l'espace agent et à l'administration.
- **Comptes usagers** : créer un compte (`/inscription/`), se connecter (`/connexion/`) et se déconnecter.
- **Liste des parkings** (`/parkings/`) : chaque parking avec son nombre de places libres, et une carte Google Maps.
- **Détail d'un parking** (`/parkings/<id>/`) : les places disponibles du parking.
- **Connexion agent** (`/agent/login/`) : réservée aux comptes agents.
- **Vérification de plaque** (`/agent/plaque/`) : l'agent saisit une plaque (format `AA-123-AA`) et voit si le véhicule a une réservation en cours, sur quelle place et dans quel parking.
- **Statistiques** (`/agent/statistiques/`) : nombre de places occupées par parking et historique de l'occupation.
- **Administration** (`/admin/`) : ajouter, modifier ou supprimer des parkings, des places et des réservations.

Règles déjà en place :
- une plaque ne peut avoir qu'une seule réservation active à la fois ;
- une place devient automatiquement indisponible quand elle est réservée, et disponible quand la réservation se termine.

> Pas encore disponible : réserver une place depuis le site.

## Lancer les tests
```bash
uv run python manage.py test
```

## Suivi de l'équipe

### En cours
- Mettre les points des parkings sur la carte, avec le focus sur une ville en particulier.
