# Parking King — gestion de places de parking

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

### Réinitialisation du mot de passe
Un compte doit avoir une adresse e-mail renseignée (à l'inscription ou dans « Mon compte »). En configuration locale, Django affiche le lien de réinitialisation dans le terminal. Pour envoyer les e-mails via SMTP, définir les variables d'environnement `DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` et `DEFAULT_FROM_EMAIL`.

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
Cette commande crée 4 parkings et 40 places (dont deux places PMR par parking), des véhicules actuellement stationnés, un historique de départs, environ 30 jours de réservations passées (pour l'analyse de l'affluence), deux contraventions de démonstration créées par `agent1` et `agent2` (dont une associée au compte `demo`) et un récapitulatif de stationnement terminé pour `demo` : 3 h 30 réservées et 2 h 16 réellement stationnées. Le récapitulatif inclut le montant final et le remboursement calculés au tarif du parking. Les contraventions de démonstration sont actualisées si la commande est relancée. Elle crée aussi les comptes suivants :

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
- **Paramètres du compte** (`/parametres/`) : modifier l’adresse e-mail, le numéro de téléphone, le modèle facultatif du véhicule et la déclaration PMR ; activer ou désactiver les rappels de stationnement ; accéder au changement de mot de passe et à la gestion du moyen de paiement simulé. La suppression du compte demande une confirmation et la saisie exacte du nom de compte ; elle est refusée si un stationnement est en cours ou si l’usager a reçu une contravention. Les contraventions créées par un agent ne bloquent pas sa suppression et conservent le nom de leur créateur dans l’historique. Les données de carte bancaire ne sont jamais conservées.
- **Justificatif PMR** : déclarer dans « Paramètres » la présence d’un justificatif PMR. Sans cette déclaration, la réservation d’une place PMR est désactivée sur la fiche parking et refusée côté serveur. Lors du contrôle, l’agent voit si le justificatif est déclaré ou manquant.
- **Avis de contravention** : six types prédéfinis ont leur motif et montant indicatif (50 €, 135 €, 35 €, 50 €, 75 € et 50 €) ; le type « Autres » demande à l’agent un motif et un montant entre 30 € et 200 €. Ces montants sont des valeurs de démonstration. Chaque avis a un numéro unique, un commentaire et un statut. Le créateur et l’avis restent visibles dans l’historique partagé des agents après un changement de compte. L’usager concerné peut consulter son avis et déposer une opposition dans les 30 jours ; l’agent retrouve les détails depuis les statistiques et l’historique.
- **Mot de passe oublié** (`/mot-de-passe-oublie/`) : recevoir un lien de réinitialisation par e-mail si l'adresse est connue, puis choisir un nouveau mot de passe.
- **Liste des parkings** (`/parkings/`) : chaque parking avec son nombre de places libres (badge « presque complet » / « complet »), son tarif, sa durée maximale et ses horaires, et une carte Google Maps. Des filtres permettent de chercher par tarif, durée maximale, nombre minimum de places libres et heure d'ouverture. Le bouton « Voir sur la carte » centre la carte sur le parking choisi.
- **Places PMR** : l'administration permet de marquer une place comme PMR. Le filtre « Places PMR disponibles » met en évidence sur la carte les parkings ayant au moins une place PMR libre.
- **Favoris** : ajouter ou retirer un parking des favoris depuis la liste, puis consulter les parkings enregistrés dans « Mes favoris ».
- **Détail d'un parking** (`/parkings/<id>/`) : carte de localisation, places disponibles, tarif horaire, durée maximale et horaires. Chaque place a un bouton « Réserver ».
- **Réservation et paiement simulé** (`/parkings/<id>/places/<id>/reserver/`) : l'usager saisit sa plaque (format `AA-123-AA`) et compose la durée souhaitée en jours, heures et minutes ; la limite du parking est vérifiée en minutes. Pour une limite inférieure à 24 heures, le champ des jours est masqué et les autres champs sont plafonnés à la durée maximale. Le montant estimé est calculé et l’usager valide avec un moyen de paiement simulé (nouvelle carte ou carte déjà enregistrée). Une référence de paiement est fournie.
- **Moyens de paiement** (`/moyens-de-paiement/`) : enregistrer un moyen de paiement simulé. Les informations de carte ne sont jamais conservées.
- **Mes réservations** (`/mes-reservations/`) : consulter ses réservations, recevoir un rappel dans l'application 15 minutes avant la fin si les notifications sont activées dans les paramètres, les annuler, confirmer son arrivée, prolonger en choisissant librement le nombre de jours, heures et minutes (dans la limite du parking), puis déclarer son départ.
- **Récapitulatif** (`/mes-reservations/<id>/`) : arrivée, départ, durée réservée, durée réelle en minutes, montant initialement payé, montant final calculé au prorata du temps réellement utilisé, remboursement éventuel et référence de paiement.

### Côté agent
- **Accès professionnel** (`/acces-professionnel/`) : choix entre l'espace agent et l'administration.
- **Connexion agent** (`/agent/login/`) : réservée aux comptes du groupe « Agents ».
- **Tableau de bord agent** (`/agent/`) : accès aux outils de l'agent.
- **Vérification de plaque** (`/agent/plaque/`) : l'agent saisit une plaque, voit si le véhicule a une réservation en cours (et si l'arrivée a été confirmée), vérifie la déclaration de justificatif PMR sur une place PMR et peut clôturer le stationnement.
- **Contraventions** (`/agent/plaque/`) : pour une plaque sans réservation active, l'agent peut enregistrer un motif et choisir le parking où l'infraction a été constatée. L'historique est disponible depuis l'espace agent.
- **Occupation en temps réel et contraventions** (`/agent/statistiques/`) : taux d'occupation global et par parking, alerte dès 80 % d'occupation par parking, liste des véhicules stationnés (place, plaque, arrivée, fin prévue) et historique des derniers mouvements (réservations, départs, annulations) avec les plaques. La plaque permet d'ouvrir directement sa localisation. La liste des contraventions affiche leur date, numéro, véhicule, motif, montant, statut et agent ; le lien « Voir le détail » ouvre l'avis complet (numéro, véhicule, motif, montant, date, lieu, commentaire et statut).
- **Analyse de l'affluence** (`/agent/affluence/`) : sur 7, 30 ou 90 jours, pour un parking ou tous, le pic d'occupation et le nombre de réservations par jour, l'affluence par heure et par jour de la semaine (heure de pointe, jour le plus chargé).

### Administration
- **Administration** (`/admin/`) : ajouter, modifier ou supprimer des parkings (tarif, durée maximale, horaires, coordonnées GPS), des places, des réservations, des favoris et consulter les contraventions.

### Règles en place
- une plaque ne peut avoir qu'une seule réservation active à la fois ;
- une place devient automatiquement indisponible quand elle est réservée, et disponible quand la réservation se termine ;
- la réservation est impossible si le tarif du parking n'est pas renseigné ;
- les pages usagers demandent d'être connecté, et les pages agent sont réservées au groupe « Agents » (vérifié côté serveur).

## Lancer les tests
```bash
uv run python manage.py test
```

## Tâches à faire

### Usager
- **Notification avant expiration** : régler le rappel à **10 minutes** avant la fin. Le rappel actuel s’affiche à 15 minutes.
- **Refus de paiement** : simuler un paiement refusé avec un message explicite et permettre de réessayer ou de choisir un autre moyen de paiement, sans enregistrer de vraies données bancaires.
- **Commentaire usager** : permettre à l’usager d’ajouter un commentaire sur un stationnement terminé ou une contestation, l’horodater et le rendre visible à l’agent concerné.
- **QR code du stationnement** : générer et afficher un QR code unique pour un stationnement actif, puis le rendre invalide à la fin du stationnement.

### Agent
- **Scanner le QR code** : permettre à l’agent de scanner le QR code d’un stationnement et d’afficher son statut ; signaler les codes invalides ou expirés.
