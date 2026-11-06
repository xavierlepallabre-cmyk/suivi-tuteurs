# Suivi Tuteurs — v0.1

Application de suivi des apprentis et de prise de rendez-vous avec leurs tuteurs. Xavier Le Pallabre.

## Ce qui fonctionne

- Espace enseignant protégé par mot de passe.
- Création et modification des fiches : apprenti, classe, entreprise, tuteur, email et adresse de visite.
- Import CSV UTF-8 et Excel `.xlsx` (première feuille, 500 apprentis maximum).
- Lien personnel par apprenti, avec renouvellement et révocation immédiate de l’ancien lien.
- Disponibilités hebdomadaires récurrentes et dates ponctuelles.
- Portail tuteur : disponibilités, demande de rendez-vous, consultation du statut.
- Validation ou refus manuel de toutes les demandes ; annulation des rendez-vous confirmés.
- Contrôle des conflits côté serveur au moment de la validation.
- Conservation des données dans SQLite, partagées entre tous les appareils connectés au même serveur.

Une visite sur site réserve une demi-journée entière, déplacement compris : 8 h–12 h ou 13 h–17 h, heure de Paris. En v0.1, les appels et visios réservent aussi une demi-journée ; l’heure précise se convient directement. Les disponibilités sont proposées sur 90 jours. Les demandes en attente ne bloquent pas le planning ; un seul rendez-vous confirmé est autorisé par demi-journée.

## Démarrage sur Windows

Installer Python 3.11 ou supérieur, puis télécharger ce dépôt (Code → Download ZIP) et extraire l’archive. Dans un terminal ouvert dans le dossier :

```powershell
py -m pip install -r requirements.txt
py server.py --set-password
py server.py
```

Ouvrir **http://127.0.0.1:8000** et se connecter avec le mot de passe créé. Aucun mot de passe par défaut. Le paquet `tzdata` fournit le fuseau Europe/Paris, notamment sur Windows. Aucun environnement Node ou outil de compilation n’est nécessaire pour utiliser l’application.

Sur Linux ou macOS, remplacer `py` par `python3` et utiliser un environnement virtuel si nécessaire.

## Premier essai

1. Ajouter une disponibilité dans l’onglet **Disponibilités**.
2. Créer un apprenti ou importer [le CSV d’exemple](exemples/apprentis.csv).
3. Copier le lien personnel affiché. Le conserver avant de fermer la fenêtre : le serveur ne garde que son empreinte, le lien original n’est pas récupérable.
4. Ouvrir ce lien dans un autre onglet pour essayer le portail tuteur.
5. Demander un rendez-vous puis revenir à l’espace enseignant et actualiser pour le valider.
6. Actualiser le portail tuteur pour voir la confirmation.

Le lien personnel donne accès au nom de l’apprenti, à son entreprise et à ses rendez-vous. Il doit être transmis au seul tuteur concerné. Si le lien est perdu, le renouveler depuis la fiche ; le précédent devient inutilisable. Le portail retire le jeton de la barre d’adresse après ouverture : pour revenir après un rechargement ou fermeture, rouvrir le lien conservé.

## Import

En-têtes acceptés, en minuscules :

```csv
nom;classe;entreprise;tuteur;email;adresse
```

Seule la colonne `nom` est obligatoire ; les autres peuvent être omises. Utiliser des colonnes contiguës, sans colonne sans nom. Le CSV accepte la virgule et le point-virgule ; les champs contenant le séparateur doivent être entre guillemets. Excel : format `.xlsx`, première feuille standard `sheet1`, textes ou valeurs enregistrées ; `.xls`, macros et calculs de formules ne sont pas pris en charge. Fichier limité à 2 Mo dans l’interface, contenu décompressé à 20 Mo. L’import est atomique : une ligne sans nom invalide tout le lot. Il ajoute des fiches, sans fusion ni détection de doublons. Les liens de toutes les fiches créées sont affichés après l’import.

## Accès depuis d’autres appareils

Le dépôt contient le logiciel ; **il n’est pas encore hébergé en ligne**. GitHub Pages ne peut pas exécuter ce serveur Python ou héberger sa base SQLite.

Pour un essai sur un réseau local de confiance :

```powershell
py server.py --host 0.0.0.0 --port 8000
```

Ouvrir l’adresse du PC sur ce réseau, par exemple `http://192.168.1.20:8000` si c’est réellement son adresse. Créer et copier les liens depuis cette adresse, sinon les liens commenceront par `127.0.0.1` et ne fonctionneront que sur le PC. Le pare-feu du PC doit autoriser l’accès sur le réseau privé. Laisser le serveur allumé.

Pour des tuteurs extérieurs : installer sur un serveur avec stockage persistant, derrière un reverse proxy HTTPS. Définir `PUBLIC_ORIGIN` à l’origine HTTPS exacte (sans barre finale) et `COOKIE_SECURE=1`. Le serveur écoute sur l’interface privée ; le reverse proxy assure TLS. Ne pas exposer directement le serveur HTTP Python sur Internet. Un hébergement mutualisé purement statique ou un disque éphémère ne convient pas.

Image Docker fournie pour un hébergement disposant de Docker :

```sh
docker build -t suivi-tuteurs:0.1 .
docker run --rm -it -v suivi-tuteurs-data:/data suivi-tuteurs:0.1 python server.py --set-password
docker run -d --name suivi-tuteurs -p 127.0.0.1:8000:8000 -v suivi-tuteurs-data:/data -e PUBLIC_ORIGIN=https://votre-domaine.fr -e COOKIE_SECURE=1 suivi-tuteurs:0.1
```

Remplacer le domaine par celui réellement configuré dans le reverse proxy. Ces commandes ne déploient pas automatiquement un domaine ou HTTPS.

## Données et sauvegarde

Base par défaut : `data/suivi.sqlite3`. Ne jamais la publier dans GitHub. Le dossier `data/` et les bases SQLite sont ignorés par Git. La variable `SUIVI_DB` permet de changer son emplacement. Les fiches et rendez-vous contiennent des données personnelles : limiter les accès au serveur et aux sauvegardes.

Pour une sauvegarde simple et cohérente, arrêter le serveur, copier la base, puis redémarrer. Restaurer en remplaçant la base serveur arrêté. Les sauvegardes incluent aussi les empreintes des liens et sessions : les protéger comme la base. Réinitialiser le mot de passe avec `--set-password` invalide toutes les sessions enseignant existantes.

## Vérifications

```sh
python -m unittest discover -s tests -v
node --check static/app.js
```

Les tests vérifient l’accès privé, les cookies de session, la protection intersites, les demandes, la validation avec conflit, l’annulation, la révocation des liens, la modification d’une fiche et les imports CSV/XLSX. Le workflow GitHub Actions exécute ces vérifications à chaque push et pull request.

## Limites de cette première version

- Un espace enseignant unique ; pas de comptes multiples ou récupération du mot de passe par email.
- Pas d’email automatique, synchronisation d’agenda, calcul d’itinéraire ou regroupement de visites proches.
- Pas encore de créneaux fins pour les appels et visios, d’exceptions aux récurrences, d’archivage des apprentis ou d’export de suivi.
- Les tuteurs contactent l’enseignant pour modifier ou annuler une demande.
- Le tableau de bord et les portails s’actualisent manuellement.
- Serveur conçu pour un petit usage pédagogique, avec un processus unique et une base locale persistante. La limitation des tentatives de connexion est en mémoire et se réinitialise au redémarrage.

Voir [l’architecture et l’authentification](docs/authentification.md).
