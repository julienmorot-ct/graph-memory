# 🧠 Graph Memory — MCP Knowledge Graph Service

Service de mémoire persistante basé sur un **graphe de connaissances** pour les agents IA, implémenté avec le protocole [MCP (Model Context Protocol)](https://modelcontextprotocol.io/).

Développé par **[Cloud Temple](https://www.cloud-temple.com)**.

---

## 📋 Table des matières

- [Changelog](#-changelog)
- [Concept](#-concept)
- [Fonctionnalités](#-fonctionnalités)
- [Architecture](#-architecture)
- [Prérequis](#-prérequis)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Démarrage](#-démarrage)
- [Interface Web](#-interface-web)
- [CLI (Command Line Interface)](#-cli-command-line-interface)
- [Outils MCP](#-outils-mcp)
- [Ontologies](#-ontologies)
- [API REST](#-api-rest)
- [Intégration MCP](#-intégration-mcp)
- [Sécurité](#-sécurité)
- [Structure du projet](#-structure-du-projet)
- [Dépannage](#-dépannage)
- [Licence](#-licence)

---

## 📋 Changelog

> Historique complet : voir [CHANGELOG.md](CHANGELOG.md)

### v0.6.5 — 16 février 2026 — Tool memory_query + Option --json CLI
- ✨ **Tool MCP `memory_query`** — Interrogation structurée sans LLM (données brutes pour agents IA)
- ✨ **Commande CLI `query`** — Shell interactif + mode Click
- ✨ **Option `--json` globale** — Sur 10 commandes de consultation, JSON brut sans formatage Rich
- 🐛 Fix erreur TaskGroup → rebuild Docker après ajout de tools

### v0.6.4 — 16 février 2026 — Panneau ASK amélioré
- ✨ Panneau ASK redimensionnable + Export HTML + Fix toggle Documents

### v0.6.3 — 15 février 2026 — Recherche accent-insensitive + Calibrage RAG
- ✨ Index fulltext Neo4j `standard-folding` (ASCII folding)
- 🔧 `RAG_SCORE_THRESHOLD` 0.65 → 0.58

### v0.6.2 — 15 février 2026 — Interface web + Progression CLI
### v0.6.1 — 15 février 2026 — Stabilisation ingestion gros documents
### v0.6.0 — 13 février 2026 — Chunked Graph Extraction + Métadonnées
### v0.5.2 — 9 février 2026 — Q&A Fallback RAG-only + Tokeniser robuste
### v0.5.1 — 9 février 2026 — Tokens email + hash complet
### v0.5.0 — Février 2026 — Version initiale publique

---

## 🎯 Concept

L'approche **Graph-First** : au lieu du RAG vectoriel classique (embedding → similitude cosinus), ce service extrait des **entités** et **relations** structurées via un LLM pour construire un graphe de connaissances interrogeable.

```
╔══════════════════════════════════════════════════════════════╗
║  INGESTION                                                   ║
╚══════════════════════════════════════════════════════════════╝
Document (PDF, DOCX, MD, TXT, HTML, CSV)
    │
    ├──▶ Upload S3 (stockage pérenne)
    │
    ├──▶ Extraction LLM guidée par ontologie
    │    └──▶ Entités + Relations typées → Graphe Neo4j
    │
    └──▶ Chunking sémantique + Embedding BGE-M3
         └──▶ Vecteurs → Qdrant (base vectorielle)

╔══════════════════════════════════════════════════════════════╗
║  QUESTION / RÉPONSE (Graph-Guided RAG)                       ║
╚══════════════════════════════════════════════════════════════╝
Question en langage naturel
    │
    ▼ 1. Recherche d'entités dans le graphe Neo4j
    │
    ├── Entités trouvées ? ──▶ Graph-Guided RAG
    │   │  Le graphe identifie les documents pertinents,
    │   │  puis Qdrant recherche les chunks DANS ces documents.
    │   └──▶ Contexte ciblé (graphe + chunks filtrés)
    │
    └── 0 entités ? ──▶ RAG-only (fallback)
        │  Qdrant recherche dans TOUS les chunks de la mémoire.
        └──▶ Contexte large (chunks seuls)
    │
    ▼ 2. Filtrage par seuil de pertinence (score cosinus ≥ 0.58)
    │    Les chunks non pertinents sont éliminés.
    │
    ▼ 3. LLM génère la réponse avec citations des documents sources
```

### Pourquoi un graphe plutôt que du RAG vectoriel ?

| Critère             | RAG vectoriel                       | Graph Memory                         |
| ------------------- | ----------------------------------- | ------------------------------------ |
| **Précision**       | Similitude sémantique approximative | Relations explicites et typées       |
| **Traçabilité**     | Chunks anonymes                     | Entités nommées + documents sources  |
| **Exploration**     | Recherche unidirectionnelle         | Navigation multi-hop dans le graphe  |
| **Visualisation**   | Difficile                           | Graphe interactif natif              |
| **Multi-documents** | Mélange de chunks                   | Relations inter-documents explicites |

---

## ✨ Fonctionnalités

### Extraction intelligente
- Extraction d'entités et relations guidée par **ontologie** (types d'entités/relations prédéfinis)
- Support des formats : **PDF, DOCX, Markdown, TXT, HTML, CSV**
- Déduplication par hash SHA-256 (avec option `--force` pour ré-ingérer)
- Instructions anti-hub pour éviter les entités trop génériques

### Graphe de connaissances
- Stockage Neo4j avec **isolation par namespace** (multi-tenant)
- Relations typées (pas de `RELATED_TO` générique avec l'ontologie `legal`)
- Entités liées à leurs documents sources (`MENTIONS`)
- Recherche par tokens avec stop words français

### Question/Réponse (Graph-Guided RAG)
- **Graph-Guided RAG** : le graphe identifie les documents pertinents, puis Qdrant recherche les chunks *dans* ces documents — contexte précis et ciblé
- **Fallback RAG-only** : si le graphe ne trouve rien, recherche vectorielle sur tous les chunks de la mémoire
- **Seuil de pertinence** (`RAG_SCORE_THRESHOLD=0.58`) : les chunks sous le seuil cosinus sont éliminés — pas de bruit envoyé au LLM
- **Citation des documents sources** dans les réponses (chaque entité inclut son document d'origine)
- Mode Focus : isolation du sous-graphe lié à une question

### Interface web interactive
- Visualisation du graphe avec [vis-network](https://visjs.github.io/vis-network/docs/network/)
- Filtrage avancé par types d'entités, types de relations, documents
- Panneau ASK intégré avec rendu Markdown (tableaux, listes, code)
- Mode Focus Question : isole le sous-graphe pertinent après une question

### CLI complète
- **Mode Click** (scriptable) : `python scripts/mcp_cli.py memory list`
- **Mode Shell** (interactif) : autocomplétion, historique, commandes contextuelles

### Sécurité
- Authentification Bearer Token pour toutes les requêtes MCP
- Clé bootstrap pour le premier token
- Isolation des données par mémoire (namespace Neo4j)

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Clients MCP                                  │
│   (Claude Desktop, Cline, QuoteFlow, Vela, CLI, Interface Web)       │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ HTTP/SSE + Bearer Token
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Graph Memory Service (Port 8002)                  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Middleware Layer                                              │  │
│  │  • StaticFilesMiddleware (web UI + API REST)                   │  │
│  │  • LoggingMiddleware (debug)                                   │  │
│  │  • AuthMiddleware (Bearer Token)                               │  │
│  └────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  MCP Tools (21 outils)                                         │  │
│  │  • memory_create/delete/list/stats                             │  │
│  │  • memory_ingest/search/get_context                            │  │
│  │  • question_answer                                             │  │
│  │  • document_delete                                             │  │
│  │  • storage_check/storage_cleanup                               │  │
│  │  • admin_create_token/list_tokens/revoke_token                 │  │
│  │  • system_health                                               │  │
│  └────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Core Services                                                 │  │
│  │  • GraphService (Neo4j)    • StorageService (S3)               │  │
│  │  • ExtractorService (LLM)  • TokenManager (Auth)               │  │
│  │  • EmbeddingService (BGE)  • VectorStoreService (Qdrant)       │  │
│  │  • SemanticChunker                                             │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
        ┌────────────┬─────────┼─────────┬────────────┐
        ▼            ▼         ▼         ▼            ▼
┌───────────┐ ┌───────────┐ ┌──────┐ ┌────────┐ ┌──────────┐
│  Neo4j 5  │ │ S3 (Dell  │ │LLMaaS│ │ Qdrant │ │Embedding │
│ (Graphe)  │ │ ECS,AWS…) │ │(Gen) │ │(Vector)│ │(BGE-M3)  │
└───────────┘ └───────────┘ └──────┘ └────────┘ └──────────┘
```

---

## 📦 Prérequis

- **Docker** & **Docker Compose** (v2+)
- **Python 3.11+** (pour la CLI, optionnel)
- Un **stockage S3** compatible (Cloud Temple, AWS, MinIO, Dell ECS)
- Un **LLM** compatible OpenAI API (Cloud Temple LLMaaS, OpenAI, etc.)

---

## 🚀 Installation

```bash
# Cloner le dépôt
git clone https://github.com/chrlesur/graph-memory.git
cd graph-memory

# Copier la configuration
cp .env.example .env
```

---

## ⚙️ Configuration

Éditez le fichier `.env` avec vos valeurs. Toutes les variables sont documentées dans `.env.example`.

### Variables obligatoires

| Variable               | Description                          |
| ---------------------- | ------------------------------------ |
| `S3_ENDPOINT_URL`      | URL de l'endpoint S3                 |
| `S3_ACCESS_KEY_ID`     | Clé d'accès S3                       |
| `S3_SECRET_ACCESS_KEY` | Secret S3                            |
| `S3_BUCKET_NAME`       | Nom du bucket                        |
| `LLMAAS_API_URL`       | URL de l'API LLM (compatible OpenAI) |
| `LLMAAS_API_KEY`       | Clé d'API LLM                        |
| `NEO4J_PASSWORD`       | Mot de passe Neo4j                   |
| `ADMIN_BOOTSTRAP_KEY`  | Clé pour créer le premier token      |

### Variables optionnelles (avec valeurs par défaut)

| Variable                     | Défaut         | Description                                    |
| ---------------------------- | -------------- | ---------------------------------------------- |
| `LLMAAS_MODEL`               | `gpt-oss:120b` | Modèle LLM                                     |
| `LLMAAS_MAX_TOKENS`          | `60000`        | Max tokens par réponse                         |
| `LLMAAS_TEMPERATURE`         | `1.0`          | Température (gpt-oss:120b requiert 1.0)        |
| `EXTRACTION_MAX_TEXT_LENGTH` | `950000`       | Max caractères envoyés au LLM                  |
| `MCP_SERVER_PORT`            | `8002`         | Port d'écoute                                  |
| `MCP_SERVER_DEBUG`           | `false`        | Logs détaillés                                 |
| `MAX_DOCUMENT_SIZE_MB`       | `50`           | Taille max documents                           |
| `RAG_SCORE_THRESHOLD`        | `0.58`         | Score cosinus min. pour un chunk RAG BGE-M3 (0.0-1.0) |
| `RAG_CHUNK_LIMIT`            | `8`            | Nombre max de chunks retournés par Qdrant      |
| `CHUNK_SIZE`                 | `500`          | Taille cible en tokens par chunk               |
| `CHUNK_OVERLAP`              | `50`           | Tokens de chevauchement entre chunks           |

Voir `.env.example` pour la liste complète.

---

## ▶️ Démarrage

```bash
# Démarrer les services (Neo4j + Graph Memory)
docker compose up -d

# Vérifier le statut
docker compose ps

# Vérifier la santé
curl http://localhost:8002/health

# Voir les logs
docker compose logs mcp-memory -f --tail 50
```

### Ports exposés

| Service       | Port   | Description                              |
| ------------- | ------ | ---------------------------------------- |
| Graph Memory  | `8002` | API MCP (SSE) + Interface Web + API REST |
| Neo4j Browser | `7475` | Interface d'administration Neo4j         |
| Neo4j Bolt    | `7688` | Protocole Bolt (requêtes Cypher)         |

---

## 🌐 Interface Web

Accessible à : **http://localhost:8002/graph**

### Fonctionnalités

- **Sélecteur de mémoire** : choisissez une mémoire et chargez son graphe
- **Graphe interactif** : zoom, drag, clic sur les nœuds pour voir les détails
- **Filtrage avancé** (sidebar gauche) :
  - 🏷️ **Types d'entités** : checkboxes avec pastilles couleur, compteurs
  - 🔗 **Types de relations** : checkboxes avec barres couleur
  - 📄 **Documents** : masquer/afficher par document source
  - Actions batch : Tous / Aucun / Inverser pour chaque filtre
- **Panneau ASK** (💬) : posez une question en langage naturel
  - Réponse LLM avec citations des documents sources
  - Rendu Markdown complet (tableaux, listes, code)
  - Entités cliquables → focus sur le nœud dans le graphe
- **Mode Focus** (🔬) : isole le sous-graphe lié aux entités de la réponse
  - Sortie automatique du mode Focus lors d'une nouvelle question (pas de filtrage résiduel)
- **Toggle MENTIONS** (📄) : masque/affiche les nœuds Document et les liens MENTIONS pour ne voir que les relations sémantiques
- **Modale paramètres** (⚙️) : ajustez la physique du graphe (distance, répulsion, taille)
- **Recherche locale** : filtrez les entités par texte dans la sidebar
- **Bouton Fit** (🔍) : recentre la vue sur tout le graphe

---

## 💻 CLI (Command Line Interface)

### Installation des dépendances CLI

```bash
pip install httpx httpx-sse click rich prompt_toolkit
```

### Mode Click (scriptable)

```bash
# Point d'entrée
python scripts/mcp_cli.py [COMMANDE] [OPTIONS]

# Exemples
python scripts/mcp_cli.py health
python scripts/mcp_cli.py memory list
python scripts/mcp_cli.py memory create JURIDIQUE -n "Corpus Juridique" -d "Documents contractuels" -o legal
python scripts/mcp_cli.py document ingest JURIDIQUE /path/to/contrat.docx
python scripts/mcp_cli.py ask JURIDIQUE "Quelles sont les conditions de résiliation ?"
python scripts/mcp_cli.py memory entities JURIDIQUE
python scripts/mcp_cli.py memory relations JURIDIQUE -t DEFINES
python scripts/mcp_cli.py ontologies
python scripts/mcp_cli.py storage check JURIDIQUE
```

### Mode Shell (interactif)

```bash
python scripts/mcp_cli.py shell

# Dans le shell :
mcp> list                          # Lister les mémoires
mcp> use JURIDIQUE                 # Sélectionner une mémoire
mcp[JURIDIQUE]> info               # Statistiques
mcp[JURIDIQUE]> docs               # Lister les documents
mcp[JURIDIQUE]> ingest /path/to/doc.pdf  # Ingérer un document
mcp[JURIDIQUE]> entities           # Entités par type
mcp[JURIDIQUE]> entity "Cloud Temple"    # Détail d'une entité
mcp[JURIDIQUE]> relations DEFINES  # Relations par type
mcp[JURIDIQUE]> ask Quelles sont les obligations du client ?
mcp[JURIDIQUE]> graph              # Graphe texte dans le terminal
mcp[JURIDIQUE]> limit 20           # Changer la limite de résultats
mcp> help                          # Aide
mcp> exit                          # Quitter
```

### Tableau complet des commandes

| Fonctionnalité     | CLI Click                       | Shell interactif    |
| ------------------ | ------------------------------- | ------------------- |
| État serveur       | `health`                        | `health`            |
| Lister mémoires    | `memory list`                   | `list`              |
| Créer mémoire      | `memory create ID -o onto`      | `create ID onto`    |
| Supprimer mémoire  | `memory delete ID`              | `delete [ID]`       |
| Info mémoire       | `memory info ID`                | `info`              |
| Graphe texte       | `memory graph ID`               | `graph [ID]`        |
| Entités par type   | `memory entities ID`            | `entities`          |
| Contexte entité    | `memory entity ID NAME`         | `entity NAME`       |
| Relations par type | `memory relations ID [-t TYPE]` | `relations [TYPE]`  |
| Lister documents   | `document list ID`              | `docs`              |
| Ingérer document   | `document ingest ID PATH`       | `ingest PATH`       |
| Supprimer document | `document delete ID DOC`        | `deldoc DOC`        |
| Question/Réponse   | `ask ID "question"`             | `ask question`      |
| Query structuré    | `query ID "question"`           | `query question`    |
| Vérif. stockage S3 | `storage check [ID]`            | `check [ID]`        |
| Nettoyage S3       | `storage cleanup [-f]`          | `cleanup [--force]` |
| Ontologies dispo.  | `ontologies`                    | `ontologies`        |

---

## 🔧 Outils MCP

21 outils exposés via le protocole MCP (HTTP/SSE) :

### Gestion des mémoires

| Outil           | Paramètres                                     | Description                                         |
| --------------- | ---------------------------------------------- | --------------------------------------------------- |
| `memory_create` | `memory_id`, `name`, `description`, `ontology` | Crée une mémoire avec ontologie                     |
| `memory_delete` | `memory_id`                                    | Supprime une mémoire (cascade: docs + entités + S3) |
| `memory_list`   | —                                              | Liste toutes les mémoires                           |
| `memory_stats`  | `memory_id`                                    | Statistiques (docs, entités, relations, types)      |
| `memory_graph`  | `memory_id`                                    | Graphe complet (nœuds, arêtes, documents)           |

### Documents

| Outil             | Paramètres                                         | Description                                       |
| ----------------- | -------------------------------------------------- | ------------------------------------------------- |
| `memory_ingest`   | `memory_id`, `content_base64`, `filename`, `force` | Ingère un document (S3 + extraction LLM + graphe) |
| `document_list`   | `memory_id`                                        | Liste les documents d'une mémoire                 |
| `document_get`    | `memory_id`, `filename`, `include_content`         | Métadonnées d'un document (+ contenu optionnel)   |
| `document_delete` | `memory_id`, `filename`                            | Supprime un document et ses entités orphelines    |

### Recherche et Q&A

| Outil                | Paramètres                       | Description                                           |
| -------------------- | -------------------------------- | ----------------------------------------------------- |
| `memory_search`      | `memory_id`, `query`, `limit`    | Recherche d'entités dans le graphe                    |
| `memory_get_context` | `memory_id`, `entity_name`       | Contexte complet d'une entité (voisins + docs)        |
| `question_answer`    | `memory_id`, `question`, `limit` | Question en langage naturel → réponse LLM avec sources |
| `memory_query`       | `memory_id`, `query`, `limit`    | Données structurées sans LLM (entités, chunks RAG, scores) |

### Ontologies

| Outil           | Paramètres | Description                   |
| --------------- | ---------- | ----------------------------- |
| `ontology_list` | —          | Liste les ontologies disponibles |

### Stockage S3

| Outil             | Paramètres              | Description                       |
| ----------------- | ----------------------- | --------------------------------- |
| `storage_check`   | `memory_id` (optionnel) | Vérifie cohérence graphe ↔ S3     |
| `storage_cleanup` | `dry_run`               | Nettoie les fichiers S3 orphelins |

### Administration

| Outil                 | Paramètres                            | Description                                   |
| --------------------- | ------------------------------------- | --------------------------------------------- |
| `admin_create_token`  | `client_name`, `permissions`, `email` | Crée un token d'accès                         |
| `admin_list_tokens`   | —                                     | Liste les tokens actifs                       |
| `admin_revoke_token`  | `token_hash`                          | Révoque un token                              |
| `admin_update_token`  | `token_hash`, `memory_ids`, `action`  | Modifie les mémoires d'un token (add/remove/set) |
| `system_health`       | —                                     | État de santé des services (Neo4j, S3, LLM, Qdrant, Embedding) |

---

## 📖 Ontologies

Les ontologies définissent les **types d'entités** et **types de relations** que le LLM doit extraire. Elles sont obligatoires à la création d'une mémoire.

### Ontologies fournies

| Ontologie          | Fichier                            | Entités  | Relations | Usage                          |
| ------------------ | ---------------------------------- | -------- | --------- | ------------------------------ |
| `legal`            | `ONTOLOGIES/legal.yaml`            | 22 types | 22 types  | Documents juridiques, contrats |
| `cloud`            | `ONTOLOGIES/cloud.yaml`            | —        | —         | Infrastructure cloud           |
| `managed-services` | `ONTOLOGIES/managed-services.yaml` | —        | —         | Services managés               |
| `technical`        | `ONTOLOGIES/technical.yaml`        | —        | —         | Documentation technique        |

### Format d'une ontologie

```yaml
name: legal
description: Ontologie pour documents juridiques
version: "1.0"

entity_types:
  - name: Article
    description: Article numéroté d'un contrat
  - name: Clause
    description: Clause contractuelle spécifique
  - name: Partie
    description: Partie signataire d'un contrat
  # ...

relation_types:
  - name: DEFINES
    description: Définit un concept ou une obligation
  - name: APPLIES_TO
    description: S'applique à une entité
  - name: REFERENCES
    description: Fait référence à un autre élément
  # ...

instructions: |
  Instructions spécifiques pour le LLM lors de l'extraction.
```

### Créer une ontologie personnalisée

1. Créez un fichier YAML dans `ONTOLOGIES/`
2. Définissez les types d'entités et relations pertinents
3. Ajoutez des instructions spécifiques si nécessaire
4. Créez la mémoire : `python scripts/mcp_cli.py memory create MON_ID -o mon_ontologie`

---

## 🌍 API REST

En plus du protocole MCP (SSE), le service expose une API REST. **Tous les endpoints `/api/*` requièrent un Bearer Token** (même header `Authorization` que pour MCP). Seuls `/health` et les fichiers statiques (`/graph`, `/static/`) sont publics.

### Endpoints publics (pas d'authentification)

| Méthode | Endpoint     | Description                    |
| ------- | ------------ | ------------------------------ |
| `GET`   | `/health`    | État de santé du serveur       |
| `GET`   | `/graph`     | Interface web de visualisation |
| `GET`   | `/static/*`  | Fichiers statiques (CSS, JS)   |

### Endpoints authentifiés (Bearer Token obligatoire)

| Méthode | Endpoint                 | Description                                            |
| ------- | ------------------------ | ------------------------------------------------------ |
| `GET`   | `/api/memories`          | Liste des mémoires (JSON)                              |
| `GET`   | `/api/graph/{memory_id}` | Graphe complet d'une mémoire (JSON)                    |
| `POST`  | `/api/ask`               | Question/Réponse via LLM (JSON)                        |
| `POST`  | `/api/query`             | Interrogation structurée sans LLM — données brutes (JSON) |

> **Note** : Le client web (`/graph`) stocke le token Bearer en `localStorage` et l'injecte automatiquement dans chaque appel `/api/*`. En cas de 401, un écran de login s'affiche.

### Exemple : Question/Réponse via API REST

```bash
curl -X POST http://localhost:8002/api/ask \
  -H "Authorization: Bearer VOTRE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "memory_id": "JURIDIQUE",
    "question": "Quelles sont les conditions de résiliation ?",
    "limit": 10
  }'
```

Réponse :
```json
{
  "status": "ok",
  "answer": "## Conditions de résiliation\n\n| Condition | Détail | Source(s) |\n|...",
  "entities": ["30 jours (préavis)", "Article 15 – Résiliation"],
  "source_documents": [
    {"filename": "CGA.docx", "uri": "s3://..."},
    {"filename": "CGV.docx", "uri": "s3://..."}
  ]
}
```

### Exemple : Query structuré (sans LLM)

```bash
curl -X POST http://localhost:8002/api/query \
  -H "Authorization: Bearer VOTRE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "memory_id": "JURIDIQUE",
    "query": "réversibilité des données",
    "limit": 10
  }'
```

---

## 🔌 Intégration MCP

### Avec Claude Desktop / Cline

Ajoutez dans votre configuration MCP :

```json
{
  "mcpServers": {
    "graph-memory": {
      "url": "http://localhost:8002/sse",
      "headers": {
        "Authorization": "Bearer VOTRE_TOKEN"
      }
    }
  }
}
```

### Via Python (client MCP)

```python
from mcp.client.sse import sse_client
from mcp import ClientSession
import base64

async def exemple():
    headers = {"Authorization": "Bearer votre_token"}
    
    async with sse_client("http://localhost:8002/sse", headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Créer une mémoire
            await session.call_tool("memory_create", {
                "memory_id": "demo",
                "name": "Démo",
                "description": "Mémoire de démonstration",
                "ontology": "legal"
            })
            
            # Ingérer un document
            with open("contrat.pdf", "rb") as f:
                content = base64.b64encode(f.read()).decode()
            
            await session.call_tool("memory_ingest", {
                "memory_id": "demo",
                "content_base64": content,
                "filename": "contrat.pdf"
            })
            
            # Poser une question
            result = await session.call_tool("question_answer", {
                "memory_id": "demo",
                "question": "Quelles sont les obligations du client ?",
                "limit": 10
            })
            print(result)
```

---

## 🔒 Sécurité

### Authentification

- **Protocole MCP** (SSE) : Bearer Token obligatoire dans le header `Authorization`
- **API REST** (`/api/*`) : Bearer Token obligatoire (même token que MCP)
- **Interface web** (`/graph`, `/static/*`) : accès public (le JS injecte le token depuis `localStorage`)
- **Requêtes internes** (localhost/127.0.0.1) : exemptées d'authentification pour MCP/SSE uniquement (pas pour `/api/*`)
- **Health check** (`/health`) : accès public

### Gestion des tokens

```bash
# Créer un token (via la clé bootstrap admin)
curl -X POST http://localhost:8002/sse \
  -H "Authorization: Bearer ADMIN_BOOTSTRAP_KEY" \
  # ... appel MCP admin_create_token

# Ou via la CLI
python scripts/mcp_cli.py shell
mcp> # utiliser les commandes d'admin
```

### Bonnes pratiques

1. **Changez `ADMIN_BOOTSTRAP_KEY`** en production
2. **Changez `NEO4J_PASSWORD`** en production
3. Ne commitez jamais le fichier `.env`
4. Créez des tokens avec les permissions minimales nécessaires

---

## 📁 Structure du projet

```
graph-memory/
├── .env.example              # Template de configuration (toutes les variables)
├── .gitignore                # Fichiers ignorés
├── docker-compose.yml        # Orchestration Docker (Neo4j + service)
├── Dockerfile                # Image du service
├── README.md                 # Ce fichier
├── requirements.txt          # Dépendances Python
│
├── ONTOLOGIES/               # Ontologies d'extraction
│   ├── legal.yaml            # Documents juridiques (22 types entités + relations)
│   ├── cloud.yaml            # Infrastructure cloud
│   ├── managed-services.yaml # Services managés
│   └── technical.yaml        # Documentation technique
│
├── scripts/                  # CLI et utilitaires
│   ├── mcp_cli.py            # Point d'entrée CLI (Click + Shell)
│   ├── README.md             # Documentation CLI
│   ├── test_rag_thresholds.py   # Benchmark seuils RAG
│   ├── view_graph.py         # Visualisation graphe en terminal
│   └── cli/                  # Package CLI
│       ├── __init__.py
│       ├── client.py         # Client HTTP/SSE vers le serveur MCP
│       ├── commands.py       # Commandes Click (interface scriptable)
│       ├── display.py        # Affichage Rich (tables, panels, graphe)
│       └── shell.py          # Shell interactif prompt_toolkit
│
└── src/mcp_memory/           # Code source du service
    ├── __init__.py
    ├── server.py             # Serveur MCP principal (FastMCP + outils)
    ├── config.py             # Configuration centralisée (pydantic-settings)
    │
    ├── auth/                 # Authentification
    │   ├── __init__.py
    │   ├── context.py        # ContextVar pour propager l'auth aux outils MCP
    │   ├── middleware.py     # Middlewares ASGI (Auth + Logging + Static + API REST)
    │   └── token_manager.py  # CRUD tokens dans Neo4j
    │
    ├── core/                 # Services métier
    │   ├── __init__.py
    │   ├── graph.py          # Service Neo4j (requêtes Cypher)
    │   ├── storage.py        # Service S3 (upload/download via boto3)
    │   ├── extractor.py      # Service LLM (extraction d'entités + Q&A)
    │   ├── ontology.py       # Chargement des ontologies YAML
    │   ├── models.py         # Modèles Pydantic (Entity, Document, Memory…)
    │   ├── chunker.py        # SemanticChunker (découpage articles/sections)
    │   ├── embedder.py       # EmbeddingService (BGE-M3 via LLMaaS)
    │   └── vector_store.py   # VectorStoreService (Qdrant — recherche RAG)
    │
    ├── tools/                # Outils MCP (enregistrés dans server.py)
    │   └── __init__.py
    │
    └── static/               # Interface web
        ├── graph.html        # Page principale
        ├── css/
        │   └── graph.css     # Styles (thème sombre, couleurs Cloud Temple)
        ├── js/
        │   ├── config.js     # Configuration, couleurs, état de filtrage
        │   ├── api.js        # Appels API REST
        │   ├── graph.js      # Rendu vis-network + mode Focus
        │   ├── sidebar.js    # Filtres, liste d'entités, recherche
        │   ├── ask.js        # Panneau Question/Réponse
        │   └── app.js        # Orchestration et initialisation
        └── img/
            └── logo-cloudtemple.svg
```

---

## 🔍 Dépannage

### Le service ne démarre pas

```bash
# Vérifier les logs
docker compose logs mcp-memory --tail 50

# Vérifier que Neo4j est prêt
docker compose logs neo4j --tail 20

# Vérifier la configuration
docker compose exec mcp-memory env | grep -E "S3_|LLMAAS_|NEO4J_"
```

### Erreur 401 Unauthorized

- Vérifiez que votre token est valide
- Les endpoints publics (`/health`, `/graph`, `/static/*`) ne nécessitent pas de token
- **Tous les `/api/*`** et les requêtes MCP via SSE (`/sse`) nécessitent un Bearer Token

### Page web blanche

- Accédez à `http://localhost:8002/graph` (pas `/` ni `/static/graph.html`)
- Faites un **hard refresh** : `Cmd+Shift+R` (Mac) ou `Ctrl+Shift+R` (Windows)
- Vérifiez les logs : `docker compose logs mcp-memory -f`

### L'extraction est lente ou échoue

- Vérifiez `EXTRACTION_MAX_TEXT_LENGTH` (réduisez pour les modèles avec petite fenêtre de contexte)
- Augmentez `EXTRACTION_TIMEOUT_SECONDS` si le LLM est lent
- Vérifiez les logs pour les erreurs LLM : `docker compose logs mcp-memory | grep "❌"`

### Rebuild après modification du code

```bash
docker compose build mcp-memory && docker compose up -d mcp-memory
```

---

## 📄 Licence

Ce projet est distribué sous licence **Apache 2.0**. Voir le fichier [LICENSE](LICENSE) pour plus de détails.

Développé par **[Cloud Temple](https://www.cloud-temple.com)**.

---

*Graph Memory v0.6.5 — Février 2026*
