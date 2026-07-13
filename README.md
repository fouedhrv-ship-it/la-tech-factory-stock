# La Tech Factory — surveillance stock & photos produits

Ce dépôt fait tourner automatiquement, tous les matins, un script qui :

- lit uniquement les pages publiques de https://la-tech-factory.com (aucun accès back-office, aucun identifiant utilisé) ;
- repère les produits marqués "Rupture de stock" ;
- repère les produits avec moins de 4 photos ;
- met à jour ce Google Sheet : https://docs.google.com/spreadsheets/d/1v32NNkVbxbqT7H66Cc0S95UPIDzfZ2MDqI5GbqSinEY/edit

Le tout tourne sur les serveurs de GitHub Actions, donc indépendamment de ton ordinateur — pas besoin qu'il soit allumé.

## Mise en place (à faire une seule fois)

Il faut créer un compte de service Google : une identité technique, séparée de ton compte personnel, à qui on donne uniquement le droit d'écrire dans CE Google Sheet précis. Aucun mot de passe personnel n'est utilisé nulle part.

### 1. Créer le compte de service Google

1. Va sur https://console.cloud.google.com/ (crée un projet si tu n'en as pas, gratuit).
2. Menu -> API et services -> Bibliothèque -> cherche Google Sheets API -> Activer.
3. Menu -> IAM et administration -> Comptes de service -> Créer un compte de service.
   - Nom : la-tech-factory-bot (ou ce que tu veux).
   - Pas besoin de rôle particulier au niveau du projet, clique OK/Terminer.
4. Clique sur le compte de service créé -> onglet Clés -> Ajouter une clé -> Créer une clé -> format JSON -> télécharge le fichier.
   Garde ce fichier JSON précieusement (ne le partage jamais publiquement).
5. Ouvre le fichier JSON, repère le champ "client_email" (une adresse du type xxx@xxx.iam.gserviceaccount.com).

### 2. Partager le Google Sheet avec le compte de service

1. Ouvre le Google Sheet : https://docs.google.com/spreadsheets/d/1v32NNkVbxbqT7H66Cc0S95UPIDzfZ2MDqI5GbqSinEY/edit
2. Bouton Partager -> colle l'adresse client_email récupérée à l'étape 1.5 -> donne le rôle Éditeur -> Envoyer.

### 3. Ajouter les secrets sur GitHub

Dans ce dépôt GitHub : Settings -> Secrets and variables -> Actions -> New repository secret, et crée :

- GCP_SA_KEY : colle tout le contenu du fichier JSON téléchargé à l'étape 1.4.
- SPREADSHEET_ID : 1v32NNkVbxbqT7H66Cc0S95UPIDzfZ2MDqI5GbqSinEY

### 4. Activer le workflow

Le fichier .github/workflows/update-stock.yml programme une exécution tous les jours à 6h05 (heure de Paris, été). Va dans l'onglet Actions du dépôt et clique "I understand my workflows, go ahead and enable them" si demandé.

Tu peux aussi lancer une exécution manuelle immédiatement : onglet Actions -> Actualisation stock La Tech Factory -> Run workflow.

## Fichiers

- check_stock.py — le script de crawl + mise à jour du Sheet.
- requirements.txt — dépendances Python.
- .github/workflows/update-stock.yml — la programmation GitHub Actions (cron quotidien + déclenchement manuel).

## Notes

- Le script est en lecture seule sur le site : il ne modifie rien sur la-tech-factory.com.
- Chaque exécution remplace les lignes de données des deux onglets du Sheet (l'en-tête est conservé) pour refléter l'état du jour, sans accumuler de doublons.
- Le fuseau horaire du cron est UTC ; l'heure française change entre été (UTC+2) et hiver (UTC+1) — voir le commentaire dans le fichier .yml si tu veux ajuster l'heure exacte en hiver.
