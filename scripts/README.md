# 💻 MCP Memory CLI

Client en ligne de commande pour piloter le serveur **Graph Memory MCP**.

Deux modes d'utilisation :
- **Mode Click** (scriptable) : commandes directes avec arguments et options
- **Mode Shell** (interactif) : autocomplétion, historique, commandes contextuelles

---

## Prérequis

```bash
# Dépendances CLI
pip install httpx httpx-sse click rich prompt_toolkit

# Serveur MCP Memory démarré
docker compose up -d
```

## Configuration

La CLI utilise les variables d'environnement du fichier `.env` à la racine :

| Variable | Description |
|----------|-------------|
| `MCP_SERVER_URL` | URL du serveur (défaut: `http://localhost:8002`) |
| `ADMIN_BOOTSTRAP_KEY` | Token d'authentification admin |

Ou passez-les en options : `--url` et `--token`.

---

## Mode Click (scriptable)

Point d'entrée : `python scripts/mcp_cli.py [COMMANDE] [OPTIONS]`

### Serveur

```bash
# État du serveur
python scripts/mcp_cli.py health
```

### Mémoires

```bash
# Lister les mémoires
python scripts/mcp_cli.py memory list

# Créer une mémoire (ontologie obligatoire)
python scripts/mcp_cli.py memory create JURIDIQUE -n "Corpus Juridique" -d "Contrats CT" -o legal

# Supprimer une mémoire (avec confirmation, ou -f pour forcer)
python scripts/mcp_cli.py memory delete JURIDIQUE
python scripts/mcp_cli.py memory delete JURIDIQUE -f

# Info / statistiques
python scripts/mcp_cli.py memory info JURIDIQUE

# Graphe complet (table ou JSON)
python scripts/mcp_cli.py memory graph JURIDIQUE
python scripts/mcp_cli.py memory graph JURIDIQUE -f json

# Entités par type (avec documents sources)
python scripts/mcp_cli.py memory entities JURIDIQUE

# Contexte d'une entité (relations, voisins, documents)
python scripts/mcp_cli.py memory entity JURIDIQUE "Cloud Temple"

# Relations par type (résumé ou détail)
python scripts/mcp_cli.py memory relations JURIDIQUE
python scripts/mcp_cli.py memory relations JURIDIQUE -t DEFINES
```

### Documents

```bash
# Lister les documents d'une mémoire
python scripts/mcp_cli.py document list JURIDIQUE

# Ingérer un document
python scripts/mcp_cli.py document ingest JURIDIQUE /path/to/contrat.docx

# Ingérer avec un chemin source personnalisé (ex: chemin relatif dans un repo)
python scripts/mcp_cli.py document ingest JURIDIQUE /path/to/contrat.docx --source-path "legal/contracts/contrat.docx"

# Ingérer un document (forcer la ré-ingestion)
python scripts/mcp_cli.py document ingest JURIDIQUE /path/to/contrat.docx -f

# Ingérer un répertoire entier (récursif)
# → source_path (chemin relatif) et source_modified_at (mtime) passés automatiquement
python scripts/mcp_cli.py document ingest-dir JURIDIQUE ./MATIERE/JURIDIQUE
python scripts/mcp_cli.py document ingest-dir JURIDIQUE ./docs -e '*.tmp' --force

# Supprimer un document
python scripts/mcp_cli.py document delete JURIDIQUE <document_id>
```

### Question/Réponse

```bash
# Poser une question sur une mémoire
python scripts/mcp_cli.py ask JURIDIQUE "Quelles sont les conditions de résiliation ?"

# Avec debug (affiche le JSON brut)
python scripts/mcp_cli.py ask JURIDIQUE "Quelles obligations ?" -d

# Limiter le nombre d'entités recherchées
python scripts/mcp_cli.py ask JURIDIQUE "Quelles garanties ?" -l 20
```

### Stockage S3

```bash
# Vérifier la cohérence S3/graphe
python scripts/mcp_cli.py storage check
python scripts/mcp_cli.py storage check JURIDIQUE

# Nettoyer les orphelins S3 (dry run par défaut)
python scripts/mcp_cli.py storage cleanup
python scripts/mcp_cli.py storage cleanup -f   # Suppression réelle
```

### Ontologies

```bash
# Lister les ontologies disponibles
python scripts/mcp_cli.py ontologies
```

### 🔑 Tokens d'accès

```bash
# Lister les tokens actifs (affiche le hash complet pour copier-coller)
python scripts/mcp_cli.py token list

# Créer un token
python scripts/mcp_cli.py token create quoteflow
python scripts/mcp_cli.py token create quoteflow --email user@example.com
python scripts/mcp_cli.py token create quoteflow -p read,write -m JURIDIQUE,CLOUD
python scripts/mcp_cli.py token create admin-bot -p admin -e 30

# Révoquer un token (par hash, copiez-le depuis 'token list')
python scripts/mcp_cli.py token revoke <hash>
python scripts/mcp_cli.py token revoke <hash> -f   # Sans confirmation

# Autoriser un token à accéder à des mémoires
python scripts/mcp_cli.py token grant <hash> JURIDIQUE CLOUD

# Retirer l'accès à des mémoires
python scripts/mcp_cli.py token ungrant <hash> JURIDIQUE

# Remplacer toute la liste des mémoires (vide = accès à toutes)
python scripts/mcp_cli.py token set-memories <hash> JURIDIQUE CLOUD
python scripts/mcp_cli.py token set-memories <hash>   # Accès à toutes
```

**Options de `document ingest` :**

| Option | Description | Exemple |
|--------|-------------|---------|
| `--source-path` | Chemin source personnalisé (sinon: chemin absolu du fichier) | `--source-path "legal/CGA.docx"` |
| `-f` / `--force` | Forcer la ré-ingestion même si le hash existe | `-f` |

> **Note v0.6.0** : `source_path` et `source_modified_at` (date de modification du fichier) sont passés automatiquement au serveur lors de l'ingestion. Cela permet au LLM de détecter si un fichier a changé sans télécharger le contenu.

**Options de `token create` :**

| Option | Description | Exemple |
|--------|-------------|---------|
| `--email` | Email du propriétaire | `--email user@cloud-temple.com` |
| `-p` / `--permissions` | Permissions (virgules) | `-p read,write,admin` |
| `-m` / `--memories` | Mémoires autorisées (virgules) | `-m JURIDIQUE,CLOUD` |
| `-e` / `--expires` | Expiration en jours | `-e 90` |

---

## Mode Shell (interactif)

```bash
python scripts/mcp_cli.py shell
```

Fonctionnalités :
- **Tab** : autocomplétion des commandes
- **↑/↓** : historique persistant
- **Ctrl+A/E** : début/fin de ligne
- **Ctrl+W** : supprimer un mot
- **Ctrl+C** : annuler la ligne en cours

### Commandes disponibles

#### Navigation

| Commande | Description |
|----------|-------------|
| `health` | État du serveur |
| `list` | Lister les mémoires |
| `use <id>` | Sélectionner une mémoire |
| `create <id> <onto>` | Créer une mémoire |
| `info` | Résumé de la mémoire courante |
| `graph` | Graphe complet |
| `delete [id]` | Supprimer une mémoire |

#### Documents

| Commande | Description |
|----------|-------------|
| `docs` | Lister les documents |
| `ingest <path>` | Ingérer un fichier (`--force` pour ré-ingérer). Passe automatiquement `source_path` et `source_modified_at`. |
| `ingestdir <path>` | Ingérer un répertoire (`--exclude`, `--confirm`, `--force`). Passe `source_path` (relatif) + `source_modified_at` par fichier. |
| `deldoc <id>` | Supprimer un document |

#### Exploration

| Commande | Description |
|----------|-------------|
| `entities` | Entités par type (avec documents sources) |
| `entity <nom>` | Contexte d'une entité (relations, voisins, documents) |
| `relations [TYPE]` | Sans argument : résumé. Avec type : détail |
| `ask <question>` | Poser une question |

#### Stockage

| Commande | Description |
|----------|-------------|
| `check [id]` | Vérifier cohérence S3/graphe |
| `cleanup [--force]` | Nettoyer les orphelins S3 |
| `ontologies` | Lister les ontologies |

#### 🔑 Tokens

| Commande | Description |
|----------|-------------|
| `tokens` | Lister les tokens actifs (hash complet copiable) |
| `token-create <client> [perms] [mémoires] [--email addr]` | Créer un token |
| `token-revoke <hash>` | Révoquer un token |
| `token-grant <hash> <mem1> [mem2]` | Ajouter des mémoires à un token |
| `token-ungrant <hash> <mem1> [mem2]` | Retirer des mémoires |
| `token-set <hash> [mem1] [mem2]` | Remplacer les mémoires (vide = toutes) |

**Exemples token dans le shell :**

```
🧠 no memory: tokens
🧠 no memory: token-create quoteflow --email user@example.com
🧠 no memory: token-create quoteflow read,write JURIDIQUE,CLOUD
🧠 no memory: token-revoke e4914bbb828ae97fa25c9adf0cc229273dff401b088cb2aaac900bfa1c650a24
🧠 no memory: token-grant e4914bbb... JURIDIQUE CLOUD
```

#### Configuration

| Commande | Description |
|----------|-------------|
| `limit [N]` | Voir/changer le nombre d'entités par recherche (défaut: 10) |
| `debug` | Activer/désactiver le mode debug |
| `clear` | Effacer l'écran |
| `help` | Aide |
| `exit` | Quitter |

---

## Architecture CLI

```
scripts/
├── mcp_cli.py            # Point d'entrée (Click)
├── README.md             # Ce fichier
├── cleanup_and_reingest.py  # Utilitaire de ré-ingestion
├── view_graph.py         # Visualisation graphe en terminal
└── cli/
    ├── __init__.py       # Configuration (URL, token)
    ├── client.py         # Client HTTP/SSE vers le serveur MCP
    ├── commands.py       # Commandes Click (mode scriptable)
    ├── display.py        # Affichage Rich (tables, panels, graphe, tokens)
    └── shell.py          # Shell interactif prompt_toolkit
```

### Client MCP (`client.py`)

Le client communique avec le serveur via **HTTP/SSE** (Server-Sent Events) en utilisant le protocole MCP. Il encapsule :

- `list_memories()` → outil `memory_list`
- `get_graph(memory_id)` → outil `memory_graph`
- `call_tool(name, args)` → appel MCP générique

### Affichage (`display.py`)

Utilise [Rich](https://rich.readthedocs.io/) pour un affichage élégant :
- Tables colorées (mémoires, documents, entités, tokens)
- Panels (résumé graphe, création token, erreurs)
- Markdown (réponses Q&A)

---

## Codes de retour

| Code | Signification |
|------|---------------|
| 0 | Succès |
| 1 | Erreur (serveur, réseau, paramètre) |

---

## Dépannage

### "Le serveur ne répond pas"

```bash
docker compose ps
docker compose logs mcp-memory --tail 20
```

### "401 Unauthorized"

Vérifiez votre token dans `.env` :
```bash
grep ADMIN_BOOTSTRAP_KEY .env
```

Ou passez-le en option :
```bash
python scripts/mcp_cli.py --token <votre_token> health
```

### "ModuleNotFoundError: No module named 'httpx'"

```bash
pip install httpx httpx-sse click rich prompt_toolkit
```

---

*Graph Memory CLI v0.6.2 — Février 2026*
