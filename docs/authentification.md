# Architecture et authentification

## Composants

| Composant | Fichier | Rôle |
| --- | --- | --- |
| Interface | `static/index.html`, `static/style.css` | Connexion, tableau de bord, fiches et portail tuteur |
| Client | `static/app.js` | Appels JSON de même origine, affichage des liens et formulaires |
| Serveur | `server.py`, classe `Handler` | Contrôle des sessions et liens, validation, accès SQLite |
| Persistance | `data/suivi.sqlite3` | Fiches, rendez-vous, disponibilités et empreintes des secrets |
| Initialisation | `initialize()`, `set_password()` | Schéma SQLite et création/réinitialisation du mot de passe |

Le navigateur parle directement au serveur de l’application, qui possède sa base. L’application ne demande pas de jeton GitHub et n’appelle pas l’API GitHub. Le compte GitHub sert à conserver le code, pas à authentifier les enseignants ou les tuteurs.

## Enseignant : connexion puis requêtes

1. L’opérateur exécute `python server.py --set-password` sur le serveur. La saisie utilise `getpass`, le mot de passe n’est pas écrit dans un fichier de configuration ou dans le dépôt.
2. `set_password()` impose 12 caractères, crée un sel aléatoire de 16 octets et calcule PBKDF2-HMAC-SHA256 avec 600 000 itérations. La base ne conserve que `sel:empreinte` et supprime les anciennes sessions.
3. Le formulaire appelle `POST /api/login`. Le serveur recalcule l’empreinte et utilise `hmac.compare_digest`. Après 8 échecs par adresse réseau sur 15 minutes, les essais sont temporairement limités. Derrière un proxy, l’adresse observée peut être celle du proxy : la limitation s’applique alors à tous les visiteurs de ce proxy.
4. Une connexion réussie produit un secret aléatoire de 32 octets via `secrets.token_urlsafe(32)`. Son SHA-256 et son expiration sont enregistrés dans `sessions`. Le secret brut est remis au navigateur uniquement comme cookie `suivi_session`.
5. Ce cookie est `HttpOnly`, `SameSite=Strict`, chemin `/`, avec une durée absolue de 8 heures. `COOKIE_SECURE=1` ajoute `Secure` pour HTTPS. Aucun renouvellement silencieux ou refresh token.
6. `teacher()` vérifie l’empreinte du cookie et l’expiration côté serveur avant tout accès au tableau de bord ou mutation enseignant. Une modification du navigateur ne contourne pas ces vérifications.
7. `POST /api/logout` supprime la session serveur et expire le cookie. Réinitialiser le mot de passe supprime toutes les sessions.

## Tuteur : lien personnel

1. `create_apprentice()` génère un secret aléatoire de 32 octets, conserve uniquement son SHA-256 dans `apprentices.token_hash`, et remet le secret brut à l’enseignant dans la réponse de création. L’import procède de la même façon pour chaque ligne.
2. Le client construit `/#tuteur=...` avec l’origine utilisée pour ouvrir l’application. Le fragment n’est pas transmis dans la requête HTTP initiale. Le script le lit, le retire de l’URL avec `history.replaceState` et le conserve uniquement en mémoire de l’onglet. Il n’utilise ni `localStorage` ni `sessionStorage`.
3. `POST /api/portal` transmet le secret dans le corps JSON. Le serveur recherche son empreinte et ne retourne que le nom, l’entreprise et les rendez-vous de cet apprenti, ainsi que les demi-journées libres communes. Les identités des autres apprentis ne sont pas exposées au portail.
4. `POST /api/request` utilise le même secret. Le serveur déduit l’apprenti du jeton ; le client ne choisit pas arbitrairement un identifiant d’apprenti. La demande est toujours créée avec le statut `pending`.
5. Seul l’enseignant peut appeler `POST /api/decision`. La validation revérifie la disponibilité et l’absence de rendez-vous confirmé dans une transaction SQLite `BEGIN IMMEDIATE`, ce qui empêche deux validations concurrentes sur la même demi-journée.
6. `POST /api/rotate`, réservé à l’enseignant, remplace l’empreinte par celle d’un nouveau secret : le lien précédent cesse de fonctionner. Les liens n’expirent pas automatiquement en v0.1.

Le lien est un droit d’accès : quiconque le possède peut ouvrir ce portail et proposer un rendez-vous. Il n’y a pas de seconde vérification d’identité du tuteur. Le secret original n’est pas récupérable depuis la base ; fermer la fenêtre de création sans le conserver oblige à renouveler le lien. Actualiser le portail après retrait du fragment demande de rouvrir le lien original.

## Protections et exploitation

Toutes les mutations et lectures du portail passent par des POST JSON nécessitant l’en-tête `X-Suivi-Request: 1`. Sans CORS, une autre origine ne peut pas ajouter cet en-tête au navigateur ; le serveur contrôle aussi l’en-tête `Origin` lorsqu’il est présent. `PUBLIC_ORIGIN` fixe l’origine acceptée derrière un reverse proxy HTTPS. Les cookies stricts complètent cette protection contre les requêtes intersites.

Les requêtes SQL utilisent des paramètres. Le client échappe les textes métier avant insertion HTML. Le serveur fournit une CSP sans script externe ou inline, `Cache-Control: no-store`, `Referrer-Policy: no-referrer` et `X-Content-Type-Options: nosniff`. Le serveur ne journalise pas les requêtes, mots de passe ou liens. Configurer aussi le reverse proxy pour ne pas journaliser les corps JSON ni les cookies.

Le mot de passe et les jetons transitent en clair dans le protocole HTTP applicatif : **HTTPS est requis pour un accès extérieur**. Ils ne sont pas chiffrés dans le navigateur avant envoi ; le chiffrement du transport appartient à TLS. Les données métier dans SQLite ne sont pas chiffrées par l’application. Le serveur et ses sauvegardes doivent donc être protégés. Le serveur HTTP standard, la limitation en mémoire et le compte enseignant unique sont des limites explicites de la v0.1, pas une solution d’identité institutionnelle complète.
