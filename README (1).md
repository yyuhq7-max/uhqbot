# MVP Discord Bot — Hébergement sur Render

## 📁 Fichiers
- `bot.py` — le code du bot
- `requirements.txt` — dépendances Python
- `render.yaml` — définition du service Render (déploiement automatique)
- `.gitignore`

## 🚀 Déploiement sur Render

### Option A — via `render.yaml` (recommandé)
1. Pousse ces fichiers dans un dépôt GitHub/GitLab.
2. Sur [render.com](https://render.com), clique sur **New +** → **Blueprint**.
3. Sélectionne ton dépôt : Render détecte automatiquement `render.yaml`.
4. Render te demandera de renseigner la variable `DISCORD_TOKEN` (marquée `sync: false`) : colle ton token de bot Discord.
5. Clique sur **Apply** : le déploiement se lance automatiquement.

### Option B — manuellement
1. Sur Render, **New +** → **Web Service**.
2. Connecte ton dépôt.
3. Configure :
   - **Environment** : `Python 3`
   - **Build Command** : `pip install -r requirements.txt`
   - **Start Command** : `python bot.py`
4. Dans **Environment Variables**, ajoute :
   - `DISCORD_TOKEN` = ton token de bot
5. Déploie.

## ⚙️ Pourquoi un Web Service (et pas un Background Worker) ?
Render exige que les services gratuits écoutent sur un port HTTP pour rester "actifs".
Le bot lance donc un petit serveur HTTP (`KeepAliveHandler`) sur le port fourni par Render (variable `PORT`), qui répond `"Bot Discord actif !"` à toute requête GET.

## 🔁 Système anti-veille (évite l'extinction après 15 min)
Render met en veille les Web Services **gratuits** après ~15 minutes sans requête HTTP entrante.
Le bot contourne ça grâce à une tâche de fond (`self_ping`, toutes les 10 minutes) qui s'auto-ping sur sa propre URL publique, disponible automatiquement via la variable d'environnement `RENDER_EXTERNAL_URL` (fournie par Render, aucune config nécessaire).

### Renforcer encore la fiabilité (optionnel mais recommandé)
En complément du self-ping interne, ajoute un ping externe avec un service gratuit comme [UptimeRobot](https://uptimerobot.com) :
1. Crée un moniteur **HTTP(s)**.
2. URL à surveiller : l'URL publique de ton service Render (ex : `https://mvp-discord-bot.onrender.com`).
3. Intervalle : 5 minutes.

Avoir les deux (self-ping + UptimeRobot) rend le système redondant : si l'un échoue, l'autre maintient le bot éveillé.

⚠️ Note : le plan gratuit de Render reste limité en heures d'activité par mois. Pour une disponibilité 24/7 garantie sans aucune limite, il faut passer sur un plan payant.

## 🔑 Prérequis Discord
- Dans le [Portail Développeur Discord](https://discord.com/developers/applications) → ton app → **Bot** :
  - Active **SERVER MEMBERS INTENT**
  - Active **PRESENCE INTENT**
- Le bot doit être invité (installation classique "Guild Install") sur le serveur MVP pour pouvoir vérifier l'appartenance des utilisateurs.

## 🆔 Variable d'environnement `MVP_GUILD_ID` (recommandé)
Par défaut, le bot essaie de résoudre le serveur MVP à partir du lien d'invitation `https://discord.com/invite/VV2QuuUjGR`. C'est fragile : si l'invitation expire ou est supprimée, la résolution échoue.

**Solution plus fiable** : renseigne directement l'ID du serveur dans la variable d'environnement `MVP_GUILD_ID` sur Render.

Pour récupérer cet ID :
1. Sur Discord, **Paramètres utilisateur** → **Avancés** → active **Mode développeur**.
2. Clique droit sur l'icône du serveur MVP → **Copier l'identifiant du serveur**.
3. Ajoute-le sur Render : **Environment** → **Add Environment Variable** → clé `MVP_GUILD_ID`, valeur = l'ID copié (uniquement des chiffres).

Si cette variable est définie, elle est utilisée en priorité (le lien d'invitation n'est même plus interrogé). Sinon, le bot retombe sur la résolution automatique via l'invitation.
