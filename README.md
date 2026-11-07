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
Cette commande crée 4 parkings et 40 places (dont deux places PMR par parking), 11 véhicules actuellement stationnés (7 au Centre-Ville, 2 à la Gare et 1 dans chacun des deux autres parkings), en laissant une place standard libre au Centre-Ville, un historique de départs, environ 30 jours de réservations passées (pour l'analyse de l'affluence), sept contraventions de démonstration créées par `agent1` et `agent2` (dont six associées au compte `demo`, deux déjà payées, deux en cours de contestation et une contestation acceptée avec avis annulé, visibles dans l’historique usager), cinq signalements titrés pour `demo` (un nouveau sans réponse, un danger immédiat urgent en cours et attribué à `agent1`, deux résolus avec réponse de l’équipe et un refusé avec son motif), un moyen de paiement simulé nommé « Exemple » et un récapitulatif de stationnement terminé pour `demo` : 3 h 30 réservées et 2 h 16 réellement stationnées. Le récapitulatif inclut le montant final et le remboursement calculés au tarif du parking. Les contraventions et signalements de démonstration sont actualisés si la commande est relancée. Elle crée aussi les comptes suivants :

> **Attention :** relancer `seed_data` remplace les parkings, places et réservations de la base locale par les données de démonstration. Sauvegardez vos données avant de l’exécuter.

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
Le mode daltonien renforce le contraste des états et ajoute des symboles aux messages, aux disponibilités et aux statuts de réservation, de paiement et de contravention.
- **Accueil** (`/`) : présentation du service, parcours de réservation en trois étapes, FAQ interactive, accès aux parkings, à la connexion et à l'inscription. Une fois connecté, l'usager accède à ses réservations, à ses moyens de paiement et peut se déconnecter. Liens vers l'espace agent, l'administration et l'accès professionnel.
- **Comptes usagers** : créer un compte (`/inscription/`), se connecter (`/connexion/`) et se déconnecter.
- **Paramètres du compte** (`/parametres/`) : modifier l’adresse e-mail, le numéro de téléphone, le type (voiture ou moto), le modèle (avec une liste adaptée au type) et la hauteur du véhicule. La hauteur suggérée selon le modèle est indicative, modifiable et à vérifier par l’usager. Déclarer un justificatif PMR et choisir ses préférences (parking couvert, recharge électrique) ; ces critères filtrent les résultats de recherche. Activer ou désactiver les rappels de stationnement et le mode de contraste adapté au daltonisme ; accéder au changement de mot de passe et à la gestion des moyens de paiement simulés. La suppression du compte demande une confirmation et la saisie exacte du nom de compte ; elle est refusée si un stationnement est en cours ou si l’usager a reçu une contravention. Les contraventions créées par un agent ne bloquent pas sa suppression et conservent le nom de leur créateur dans l’historique. Les données de carte bancaire ne sont jamais conservées.
- **Véhicules enregistrés** (`/mes-vehicules/`) : enregistrer plusieurs plaques et types de véhicule, puis sélectionner un véhicule lors d’une réservation. La saisie directe d’une plaque reste possible.
- **Rappels récurrents** (`/mes-habitudes-de-reservation/`) : définir un parking et un créneau hebdomadaire habituel. Une notification rappelle à l’usager de réserver ; aucune réservation ni aucun paiement n’est créé sans sa confirmation.
- **Budget mensuel** : régler un seuil dans les paramètres ; une notification dans l’application est créée lorsque les dépenses simulées nettes du mois atteignent ce montant.
- **Justificatif PMR** : déclarer dans « Paramètres » la présence d’un justificatif PMR. Sans cette déclaration, la réservation d’une place PMR est désactivée sur la fiche parking et refusée côté serveur. Lors du contrôle, l’agent voit si le justificatif est déclaré ou manquant.
- **Avis de contravention** : six types prédéfinis ont leur motif et montant indicatif (50 €, 135 €, 35 €, 50 €, 75 € et 50 €) ; le type « Autres » demande à l’agent un motif et un montant entre 30 € et 200 €. Ces montants sont des valeurs de démonstration. Lors de la création, l’agent choisit un parking puis une place de ce parking ; le lieu et la place sont conservés dans l’avis. Chaque avis a un numéro unique, un commentaire, un statut de paiement et une photo facultative. Chaque photo est accessible uniquement aux agents. L’usager concerné peut consulter et payer l’avis avec le paiement simulé, puis déposer une opposition dans les 30 jours ; l’agent retrouve l’état du paiement et les contestations depuis l’historique partagé.
- **Signalement d’un problème** (`/signaler-un-probleme/`) : signaler une place occupée, un équipement en panne, un danger immédiat, une information incorrecte, un objet oublié ou un véhicule endommagé. L’usager peut indiquer la priorité souhaitée ; un danger immédiat est toujours classé urgent. Les signalements d’objet oublié ou de véhicule endommagé sont rattachés à une réservation de l’usager.
- **Mes signalements** (`/mes-signalements/`) : consulter séparément tous ses signalements titrés, leur état et leur priorité, puis ouvrir chaque ticket pour lire l’historique des échanges. Répondre à l’équipe notifie les agents ; répondre à un ticket résolu ou refusé le rouvre automatiquement. Un agent doit expliquer tout refus.
- **Notifications** (`/mes-notifications/`) : consulter les alertes dans son espace, notamment lorsqu’une place d’un parking en liste d’attente se libère ou qu’un agent répond à un signalement. Le nombre de notifications non lues apparaît dans le menu.
- **Mot de passe oublié** (`/mot-de-passe-oublie/`) : recevoir un lien de réinitialisation par e-mail si l'adresse est connue, puis choisir un nouveau mot de passe.
- **Liste des parkings** (`/parkings/`) : chaque parking avec son nombre de places libres (badge « presque complet » / « complet »), son tarif, sa durée maximale, ses horaires, son niveau de couverture, sa hauteur maximale et la présence de bornes de recharge, ainsi qu’une carte Google Maps. Les préférences du compte filtrent les résultats. La disponibilité se rafraîchit automatiquement toutes les 30 secondes et affiche l'heure de son dernier changement. Des filtres permettent de chercher par tarif, durée maximale, nombre minimum de places libres et heure d'ouverture. Le bouton « Voir sur la carte » centre la carte sur le parking choisi. Sélectionner de deux à trois parkings puis choisir « Comparer les parkings » ouvre un tableau comparatif de leurs tarifs, disponibilités, horaires, équipements, accessibilité et avis.
- **Liste d’attente** : lorsqu’un parking est complet, rejoindre sa liste depuis la fiche ou la liste des parkings ; tous les inscrits reçoivent une notification dans leur espace lorsqu’une place se libère.
- **Créneau de liste d’attente** : préciser la période recherchée. Une notification est envoyée si une place se libère pendant ce créneau.
- **Alertes de disponibilité des favoris** : choisir un seuil de places libres et recevoir une notification dans l’application lorsque ce seuil est atteint. Chaque seuil génère une alerte unique jusqu’à sa modification ou sa désactivation.
- **Accessibilité des parkings** : les fiches affichent les informations disponibles sur l’accès sans marche, les ascenseurs et les toilettes accessibles. Ces caractéristiques sont administrées dans Django.
- **Avis après stationnement** : après une réservation terminée, l’usager peut noter le parking et laisser un commentaire ; les avis apparaissent sur la fiche parking.
- **Places PMR** : l'administration permet de marquer une place comme PMR. Le filtre « Places PMR disponibles » met en évidence sur la carte les parkings ayant au moins une place PMR libre.
- **Favoris** : ajouter ou retirer un parking des favoris depuis la liste, puis consulter les parkings enregistrés dans « Mes favoris ».
- **Détail d'un parking** (`/parkings/<id>/`) : carte de localisation, places disponibles, tarif horaire, durée maximale et horaires. La liste des places et leur nombre se rafraîchissent automatiquement toutes les 30 secondes. Chaque place a un bouton « Réserver ».
- **Réservation et paiement simulé** (`/parkings/<id>/places/<id>/reserver/`) : l'usager saisit sa plaque (format `AA-123-AA`), choisit la date et l’heure de début ainsi qu’une durée en jours, heures et minutes ; la limite du parking est vérifiée en minutes. Le type de véhicule du profil est conservé sur la réservation. Le montant estimé est calculé et l’usager valide avec un moyen de paiement simulé (nouvelle carte ou carte déjà enregistrée). Une référence de paiement est fournie ; aucune donnée de carte n’est enregistrée.
- **Moyens de paiement** (`/moyens-de-paiement/`) : enregistrer plusieurs moyens de paiement simulés avec un nom pour les distinguer, les choisir lors d’une réservation et les supprimer. Les informations de carte ne sont jamais conservées.
- **Mes réservations** (`/mes-reservations/`) : consulter ses réservations, recevoir un rappel dans l’application 10 minutes avant la fin si les notifications sont activées, annuler une réservation planifiée gratuitement jusqu’à 30 minutes avant son début (au-delà, le montant payé est conservé comme frais simulés), prolonger en choisissant le nombre de jours, heures et minutes (dans la limite du parking), afficher un QR code renouvelé toutes les 30 secondes avec un code de vérification de 8 caractères, puis déclarer son départ. Pour une réservation planifiée, le chronomètre commence lorsque l’agent valide le QR code à partir de l’heure prévue ; l’usager ne peut pas confirmer lui-même l’arrivée. Si un agent refuse la réservation avant l’arrivée, il doit indiquer un motif ; l’usager en est informé et le paiement simulé est intégralement remboursé.
- **Absence à l’arrivée** : si l’agent ne valide pas le QR dans les 30 minutes après le début prévu, la réservation expire, la place est libérée et le montant simulé reste dû. Planifier la commande `expire_late_reservations` (voir ci-dessous) pour traiter les absences même sans visite du site.
- **Mes dépenses et remboursements** (`/mes-depenses/`) : consulter les paiements simulés de réservations, prolongations et contraventions, ainsi que les remboursements et le solde net.
- **Arrivée tardive** : l’usager peut signaler son retard une fois ; le délai accordé est configurable par parking (30 minutes par défaut) et la place est libérée si l’arrivée n’est pas confirmée à temps.
- **Mon historique** (`/mon-historique/`) : retrouver simplement ses réservations et ses contraventions dans une seule liste chronologique.
- **Récapitulatif** (`/mes-reservations/<id>/`) : arrivée, départ, durée réservée, durée réelle en minutes, montant initialement payé, montant final calculé au prorata du temps réellement utilisé, remboursement éventuel et référence de paiement.
- **Annulation depuis le récapitulatif** : annuler une réservation non commencée après confirmation ; le récapitulatif rappelle si l’annulation est gratuite ou si les frais simulés seront conservés.
- **Historique des modifications** : consulter dans le récapitulatif les prolongations, annulations, départs et clôtures par un agent.

### Côté agent
- **Accès professionnel** (`/acces-professionnel/`) : choix entre l'espace agent et l'administration.
- **Connexion agent** (`/agent/login/`) : réservée aux comptes du groupe « Agents ».
- **Tableau de bord agent** (`/agent/`) : accès aux outils de l'agent.
- **Signalements usagers** (`/agent/signalements/`, également accessible depuis le menu « Espace agent ») : rechercher par titre ou description, filtrer par état, parking et période de modification ; les tickets les plus récemment modifiés s’affichent en premier avec leur dernière activité. Consulter les indicateurs par état et les tickets en attente depuis plus de 24 heures, ouvrir chaque dossier, changer son statut et ajouter un commentaire visible par l’usager. Un motif est obligatoire pour refuser un ticket et une confirmation est requise avant de le résoudre ou de le refuser. Les réponses et changements d’état créent une notification pour l’usager ; les réponses des usagers notifient les agents.
- **Triage des signalements** : attribuer un ticket à un agent et régler sa priorité. Les dangers immédiats sont urgents par défaut. Des dossiers du même parking et du même type, portant sur la même place ou des titres proches, sont proposés comme doublons possibles ; la fusion reste une décision manuelle.
- **Vérification de plaque** (`/agent/plaque/`) : l'agent saisit une plaque, voit si le véhicule a une réservation en cours (et si l'arrivée a été confirmée), vérifie la déclaration de justificatif PMR sur une place PMR et peut clôturer le stationnement. Avant l’arrivée, il peut refuser une réservation en saisissant un motif ; le paiement simulé est alors intégralement remboursé, l’usager est notifié, la place est libérée et l’action est conservée dans les historiques.
- **Validation QR d’arrivée** : scanner le QR d’une réservation planifiée ouvre une page de contrôle réservée à l’agent ; à partir de l’heure prévue, sa validation démarre le chronomètre. Un QR invalide, expiré ou lié à une réservation terminée est refusé. Il s’agit d’un parcours logiciel ; aucune barrière physique n’est intégrée.
- **Contraventions** (`/agent/plaque/`) : pour une plaque sans réservation active, l'agent peut enregistrer un motif et choisir le parking où l'infraction a été constatée. L'historique est disponible depuis l'espace agent.
- **Occupation en temps réel et contraventions** (`/agent/statistiques/`) : graphique SVG accessible du taux d'occupation par parking, alerte dès 80 % d'occupation, liste des véhicules effectivement stationnés (place, plaque, arrivée, fin prévue) et historique des derniers mouvements avec les plaques. Les réservations futures ne sont pas comptées comme des véhicules déjà stationnés. La liste des contraventions affiche leur date, numéro, véhicule, motif, montant, état de paiement, contestation et agent ; le détail permet aussi à l’agent de consulter les contestations et la photo facultative.
- **Analyse de l'affluence** (`/agent/affluence/`) : sur 7, 30 ou 90 jours, pour un parking ou tous, le pic d'occupation et le nombre de réservations par jour, l'affluence par heure et par jour de la semaine (heure de pointe, jour le plus chargé).
- **Tableau de bord admin** (`/administration/tableau-de-bord/`) : occupation par parking, réservations actives, signalements à traiter, liste d’attente et signalements récents. Réservé au personnel d’administration ; les signalements sont modifiables depuis l’admin Django.

### Administration
- **Administration** (`/admin/`) : ajouter, modifier ou supprimer des parkings (tarif, durée maximale, horaires, coordonnées GPS, couverture, hauteur maximale, bornes de recharge et délai de retard), des places, des réservations, des favoris et consulter les contraventions et signalements.
- **Horaires exceptionnels** : créer dans l’administration une fermeture exceptionnelle ou des horaires différents pour une date donnée. Le changement est affiché sur la fiche parking et les réservations incompatibles sont refusées.

### Règles en place
- une plaque ne peut avoir qu'une seule réservation active à la fois ;
- une place devient automatiquement indisponible quand elle est réservée, et disponible quand la réservation se termine ;
- une réservation immédiate peut être annulée avant l’arrivée ; une réservation planifiée est remboursée si elle est annulée au moins 30 minutes avant son début, sinon le montant prévu est conservé ;
- l’arrivée d’une réservation planifiée est déclenchée par la validation du QR par un agent à partir de l’heure prévue ; passé le délai de 30 minutes sans validation, la réservation expire et la place est libérée sans remboursement ;
- une réservation reste active sans limite si l’usager ne signale pas de retard ; après un signalement, le délai configuré par parking démarre et la réservation est libérée s’il expire avant la confirmation d’arrivée ;
- la réservation est impossible si le tarif du parking n'est pas renseigné ;
- les pages usagers demandent d'être connecté, et les pages agent sont réservées au groupe « Agents » (vérifié côté serveur).

## Lancer les tests
```bash
uv run python manage.py test
```

Le traitement des retards est aussi effectué lors des consultations de parkings et des réservations. Pour libérer les places même sans consultation, planifier `uv run python manage.py expire_late_reservations` avec le Planificateur de tâches Windows (par exemple toutes les minutes).
Pour envoyer les rappels hebdomadaires et traiter les créneaux de liste d’attente ou les alertes de disponibilité, planifier aussi `uv run python manage.py send_recurring_reservation_reminders` et `uv run python manage.py check_parking_availability_notifications` (par exemple toutes les minutes).
