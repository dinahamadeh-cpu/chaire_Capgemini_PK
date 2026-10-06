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

- **Accueil** (`/`) : choisir de se connecter en tant qu'agent ou de continuer en tant qu'usager.
- **Connexion agent** (`/agent/login/`) : réservée aux comptes agents.
- **Vérification de plaque** (`/agent/plaque/`) : l'agent saisit une plaque (format `AA-123-AA`) et voit si le véhicule a une réservation en cours, sur quelle place et dans quel parking.
- **Statistiques** (`/agent/statistiques/`) : nombre de places occupées par parking et historique de l'occupation.
- **Administration** (`/admin/`) : ajouter, modifier ou supprimer des parkings, des places et des réservations.

Règles déjà en place :
- une plaque ne peut avoir qu'une seule réservation active à la fois ;
- une place devient automatiquement indisponible quand elle est réservée, et disponible quand la réservation se termine.

> Pas encore disponible : la partie usager (réserver une place sans compte).

## Lancer les tests
```bash
uv run python manage.py test
```
