# Instructions du projet

## Contexte

Application web de gestion de places de parking.&#x20;

Stack actuelle :

- Python ;
- Django ;
- SQLite ;
- templates Django ;
- tests avec `django.test.TestCase`.

## Règles de développement

- Garder l’implémentation simple et adaptée à un projet étudiant.
- Ne pas ajouter de dépendance sans besoin réel.
- Ne pas introduire React, HTMX, une API REST ou des microservices sans décision explicite de l’équipe.
- Utiliser les fonctionnalités intégrées de Django lorsque cela suffit.
- Vérifier les permissions côté serveur.
- Ne jamais stocker de vrais moyens de paiement.
- Ne pas modifier ou supprimer des fichiers sans rapport avec la tâche.

## Commandes utiles

Attention : installer uv avant de lancer ces lignes, cela va créer un .venv.
```bash
pip install uv
```
Puis lancer grâce à  :
```bash
uv run python manage.py runserver
uv run python manage.py makemigrations
uv run python manage.py migrate
uv run python manage.py test
```

## Vérification

Toute modification doit être vérifiée avec :

```bash
uv run python manage.py test
```

Si une commande ou un choix technique important change, mettre à jour ce fichier.
