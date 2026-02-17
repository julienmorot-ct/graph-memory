# Changelog

Toutes les modifications notables de ce projet sont documentées dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/),
et ce projet adhère au [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.2.2] — 2026-02-17

### 🔀 Fix HTTP 421 — Connexion client à serveur distant (reverse proxy)

#### Corrigé
- **HTTP 421 "Invalid Host header" sur /sse et /messages** (`src/mcp_memory/server.py`, `src/mcp_memory/auth/middleware.py`) — Le SDK MCP Python v1.26+ (`FastMCP`) utilise `host="127.0.0.1"` par défaut. Quand host est localhost, le SDK active automatiquement `TransportSecurityMiddleware` avec `allowed_hosts=["127.0.0.1:*", "localhost:*"]`. Derrière un reverse proxy (nginx → Caddy → MCP), le `Host` header contient le domaine public (`graph-mem.mcp.cloud-temple.app`) → rejeté avec 421.
  - **Cause racine** : `mcp/server/fastmcp/server.py` ligne 166 + `mcp/server/transport_security.py`
  - **Fix principal** : `FastMCP(host=settings.mcp_server_host)` → `host="0.0.0.0"` n'est pas dans la liste `("127.0.0.1", "localhost", "::1")`, donc `TransportSecurityMiddleware` n'est pas activé.
  - **Ceinture de sécurité** : Nouveau `HostNormalizerMiddleware` ASGI normalise le Host header vers `localhost` avant le MCP SDK. Log `🔀 [Host]`.
  - Note : les routes `/api/*` n'étaient pas affectées car interceptées par `StaticFilesMiddleware` avant Starlette.

#### Amélioré
- **Messages d'erreur client** (`scripts/cli/client.py`) — Nouvelle méthode `_extract_root_cause()` qui descend récursivement dans les `ExceptionGroup`/`TaskGroup` pour extraire le vrai message d'erreur. Avant : message cryptique `"unhandled errors in a TaskGroup (1 sub-exception)"`. Après : message clair avec suggestion de diagnostic (`HostNormalizerMiddleware`, HTTP 421).

#### Fichiers modifiés
`src/mcp_memory/auth/middleware.py`, `src/mcp_memory/server.py`, `scripts/cli/client.py`, `VERSION`, `src/mcp_memory/__init__.py`

---

## [1.2.1] — 2026-02-17

### 🐛 Fix CLI production — Variables MCP_URL / MCP_TOKEN

#### Corrigé
- **CLI 401 sur serveur de production** (`scripts/cli/__init__.py`, `scripts/cli/commands.py`) — La CLI ne pouvait pas se connecter à un serveur de production distant. Double conflit de variables d'environnement :
  1. `__init__.py` lisait `MCP_SERVER_URL` (pas `MCP_URL`) comme variable d'environnement.
  2. Click déclarait `envvar="ADMIN_BOOTSTRAP_KEY"` → `load_dotenv()` chargeait le `.env` local dev (`admin_bootstrap_key_change_me`) qui écrasait le token production.
  - **Fix** : `MCP_URL` et `MCP_TOKEN` sont désormais prioritaires (fallback sur `MCP_SERVER_URL` / `ADMIN_BOOTSTRAP_KEY`). Click accepte une liste ordonnée `envvar=["MCP_TOKEN", "ADMIN_BOOTSTRAP_KEY"]`.

#### Ajouté
- **Documentation CLI production** (`scripts/README.md`) — Section Configuration réécrite : deux jeux de variables (CLI vs serveur), usage dev vs prod, fichier `~/.env.mcp-cli`.
- **Guide déploiement §15** (`DESIGN/DEPLOIEMENT_PRODUCTION.md`) — Nouvelle section "Utiliser la CLI depuis un poste distant" avec 3 options de configuration et schéma de résolution des variables.
- **`.env.example`** — Section CLI avec `MCP_URL` / `MCP_TOKEN` commentés et documentés.

#### Fichiers modifiés
`scripts/cli/__init__.py`, `scripts/cli/commands.py`, `scripts/README.md`, `DESIGN/DEPLOIEMENT_PRODUCTION.md`, `.env.example`, `VERSION`, `src/mcp_memory/__init__.py`

---

## [1.2.0] — 2026-02-16

### 💾 Backup / Restore complet + Fix storage_check

#### Ajouté
- **Système de Backup/Restore** (`backup.py`, `server.py`, `commands.py`, `shell.py`, `display.py`) — 7 nouveaux outils MCP :
  - `backup_create` : Exporte graphe Neo4j (entités, relations, documents) + vecteurs Qdrant → S3. Politique de rétention configurable (`BACKUP_RETENTION_COUNT`).
  - `backup_list` : Liste les backups disponibles avec statistiques (entités, relations, vecteurs, docs).
  - `backup_restore` : Restaure depuis un backup S3 (graphe + vecteurs), sans re-extraction LLM (~0.3s).
  - `backup_download` : Télécharge un backup en archive tar.gz (light ou avec documents originaux).
  - `backup_delete` : Supprime un backup de S3.
  - `backup_restore_archive` : **Restaure depuis une archive tar.gz locale** — re-uploade les documents S3 inclus dans l'archive + restaure graphe + vecteurs. Cycle complet validé : backup → download tar.gz → suppression totale serveur → restore depuis fichier local.
- **CLI backup complète** — 6 commandes Click (`backup create/list/restore/download/delete/restore-file`) + commandes shell interactif correspondantes.
- **Affichage Rich** (`display.py`) — `show_backup_result`, `show_backups_table`, `show_restore_result` pour un rendu formaté des opérations backup.
- **Configuration backup** (`.env.example`, `config.py`) — `BACKUP_RETENTION_COUNT` (défaut: 5 backups par mémoire).

#### Corrigé
- **`storage_check` : faux-positifs orphelins quand scopé** — `storage check JURIDIQUE` signalait 42 "orphelins" (les documents des AUTRES mémoires + les backups). Deux fixes :
  - Les fichiers `_backups/` sont maintenant exclus de la détection d'orphelins (gérés par `backup_list`).
  - Quand scopé à une mémoire, la détection d'orphelins charge les URIs de TOUTES les mémoires (pas seulement la scopée). Les documents des autres mémoires ne sont plus signalés à tort.

#### Architecture backup
- Format backup S3 : `_backups/{memory_id}/{timestamp}/` contenant `manifest.json`, `graph_data.json`, `qdrant_vectors.jsonl`, `document_keys.json`.
- Format archive tar.gz : même structure + dossier optionnel `documents/` avec les fichiers originaux.
- Couplage strict : si Qdrant ou Neo4j échoue pendant la restauration, l'opération est annulée.
- Checksum SHA-256 vérifié lors de la restauration depuis archive.

#### Fichiers ajoutés/modifiés
`src/mcp_memory/core/backup.py` (nouveau), `src/mcp_memory/server.py`, `src/mcp_memory/config.py`, `scripts/cli/commands.py`, `scripts/cli/shell.py`, `scripts/cli/display.py`, `.env.example`, `VERSION`, `src/mcp_memory/__init__.py`

---

## [1.1.0] — 2026-02-16

### 🔒 Rate Limiting + Analyse de Risques Sécurité

#### Ajouté
- **Rate Limiting WAF** (`waf/Caddyfile`, `waf/Dockerfile`) — Module `caddy-ratelimit` compilé dans l'image WAF via `xcaddy`. 4 zones de limitation par IP :
  - `/sse*` : 10 connexions/min (SSE longue durée)
  - `/messages/*` : 60 appels/min (outils MCP, burst d'un agent actif)
  - `/api/*` : 30 requêtes/min (interface web)
  - Global : 200 requêtes/min (toutes routes confondues)
  - Requêtes excédentaires → HTTP 429 (Too Many Requests)
- **Analyse de Risques Sécurité** (`DESIGN/ANALYSE_RISQUES_SECURITE.md`) — Document complet :
  - Matrice de risques par route (/sse, /messages, /api, /public)
  - Vecteurs d'attaque avec probabilité, impact, risque, mitigation
  - Risques transversaux : prompt injection, token compromise, DoS, CSP unsafe-inline
  - Conformité OWASP Top 10, SecNumCloud, RGPD
  - Recommandations priorisées (haute/moyenne/basse)
- **Script de test rate limiting** (`scripts/test_rate_limit.sh`) — Envoie 35 requêtes rapides sur `/api/memories`, vérifie que les 30 premières passent et les suivantes reçoivent HTTP 429.

#### Modifié
- **WAF Dockerfile** — Ajout du plugin `caddy-ratelimit` dans la compilation `xcaddy`.

#### Fichiers ajoutés/modifiés
`waf/Dockerfile`, `waf/Caddyfile`, `DESIGN/ANALYSE_RISQUES_SECURITE.md` (nouveau), `scripts/test_rate_limit.sh` (nouveau), `VERSION`, `src/mcp_memory/__init__.py`, `src/mcp_memory/auth/middleware.py`

---

## [1.0.0] — 2026-02-16

### 🎉 Version 1.0 — Production Ready

#### Architecture sécurisée
- **Coraza WAF** (`waf/Dockerfile`, `waf/Caddyfile`) — Image custom buildée via `xcaddy` + plugin `coraza-caddy/v2` avec OWASP Core Rule Set embarqué. Protection OWASP Top 10 (injections SQL/XSS, SSRF, path traversal, scanners).
- **Architecture réseau durcie** — Seul le port 8080 (WAF) est exposé. Neo4j, Qdrant et le service MCP sont sur un réseau Docker interne isolé (`mcp-network`). Container MCP non-root (`USER mcp`).
- **TLS Let's Encrypt natif** — Caddy gère nativement ACME/Let's Encrypt. Variable `SITE_ADDRESS` pour basculer dev (`:8080` HTTP) ↔ prod (`domaine.com` HTTPS automatique).
- **Headers de sécurité** — CSP (Content-Security-Policy), X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy, Permissions-Policy.

#### Routage WAF intelligent
- **Routes SSE/MCP sans WAF** (`handle /sse*`, `handle /messages/*`) — Coraza bufférise les réponses pour les inspecter, ce qui est incompatible avec le streaming SSE. Ces routes sont servies en reverse proxy direct (authentification gérée côté serveur MCP par token Bearer).
- **Routes web avec WAF** (`handle`) — API REST (`/api/*`), fichiers statiques, health et graphe protégés par Coraza WAF + OWASP CRS.
- **Timeouts calibrés** — SSE : timeout 0 (connexions MCP longues), ingestion : 1800s (30 min pour gros documents), API REST : 300s.

#### CLI adaptée
- **Port par défaut 8080** — La CLI pointe désormais sur le WAF (`http://localhost:8080`) au lieu du service interne (`http://localhost:8002`).

#### Fichiers ajoutés/modifiés
`waf/Dockerfile` (nouveau), `waf/Caddyfile`, `docker-compose.yml`, `Dockerfile`, `scripts/cli/__init__.py`, `scripts/view_graph.py`, `scripts/README.md`, `src/mcp_memory/auth/middleware.py`, `VERSION`

---

## [0.6.6] — 2026-02-16

### Audit sécurité + WAF Coraza + Hardening Docker

#### Ajouté
- **Coraza WAF** (`waf/Caddyfile`, `docker-compose.yml`) — Reverse proxy sécurisé avec OWASP Core Rule Set (CRS). Protection contre injections SQL/XSS, path traversal, SSRF, scanners. Headers de sécurité (CSP, HSTS, X-Frame-Options, Permissions-Policy). Seul port exposé : 8080 (WAF).
- **Support TLS Let's Encrypt natif** — Caddy (intégré dans l'image Coraza CRS) gère nativement ACME/Let's Encrypt. Variable `SITE_ADDRESS` pour basculer dev (`:8080` HTTP) ↔ prod (`domaine.com` HTTPS automatique). Pas besoin de nginx/certbot.
- **Rapport d'audit** (`AUDIT_SECURITE_2026-02-16.md`) — Audit complet : 3 vulnérabilités critiques, 5 élevées, 7 moyennes identifiées et corrigées.

#### Corrigé (sécurité)
- **Container root** (`Dockerfile`) — Ajout `USER mcp` non-root (le service tournait en root dans le container).
- **Ports Neo4j/Qdrant exposés** (`docker-compose.yml`) — Supprimés. Neo4j et Qdrant ne sont plus accessibles depuis l'extérieur (réseau Docker interne uniquement). Ports debug commentés sur 127.0.0.1.
- **Timeouts WAF calibrés** — SSE : timeout 0 (connexions MCP longues), ingestion : 1800s (30 min pour gros documents avec chain-of-thought LLM), API REST : 300s.

#### Corrigé (config)
- **`EXTRACTION_MAX_TEXT_LENGTH` refactorisé** (`extractor.py`) — N'était plus utile avec le chunking (code mort). Transformé en garde-fou explicite : rejette avec `ValueError` les documents trop volumineux AVANT le chunking, au lieu de tronquer silencieusement.
- **`.env.example` : `EXTRACTION_CHUNK_SIZE`** — Corrigé de 200000 → **25000** (valeur réelle dans config.py depuis v0.6.1).
- **`.env` nettoyé** — Supprimé le override `EXTRACTION_MAX_TEXT_LENGTH=120000`, les défauts config.py (950K) sont maintenant utilisés. Structure alignée sur `.env.example`.

#### Fichiers modifiés/créés
`Dockerfile`, `docker-compose.yml`, `waf/Caddyfile` (nouveau), `.env`, `.env.example`, `extractor.py`, `AUDIT_SECURITE_2026-02-16.md` (nouveau), `VERSION`

---

## [0.6.5] — 2026-02-16

### Tool memory_query + Option --json CLI

#### Ajouté
- **Tool MCP `memory_query`** (`server.py`) — Interrogation structurée sans LLM. Même pipeline que `question_answer` (graphe fulltext + RAG vectoriel) mais retourne les données brutes : entités enrichies (relations, voisins, documents sources), chunks RAG avec scores, statistiques. Idéal pour les agents IA qui construisent leur propre réponse.
- **Commande CLI `query`** (`shell.py`, `commands.py`) — Nouvelle commande dans le shell interactif et en mode Click. Affichage formaté Rich avec entités, chunks RAG triés par score, et documents sources.
- **Affichage `show_query_result()`** (`display.py`) — Rendu Rich dédié pour les résultats de `memory_query` : panel par entité (relations, voisins), table RAG chunks, panel documents sources.
- **Option `--json` globale** (`shell.py`) — Utilisable sur toute commande de consultation (`list`, `info`, `graph`, `docs`, `entities`, `entity`, `relations`, `ask`, `query`). Affiche le JSON brut du serveur sans formatage Rich. Détection automatique n'importe où dans la ligne (`query --json ma question` ou `--json list`). Idéal pour scripting et pipe vers `jq`.

#### Corrigé
- **Erreur TaskGroup sur `query`** — Le serveur Docker n'avait pas le nouveau code (`memory_query` non enregistré). Rebuild Docker nécessaire après ajout de nouveaux tools MCP.

#### Fichiers modifiés
`server.py`, `shell.py`, `display.py`, `commands.py`

---

## [0.6.4] — 2026-02-16

### Panneau ASK amélioré + Fix toggle Documents

#### Ajouté
- **Panneau ASK redimensionnable** (`ask.js`, `graph.css`, `graph.html`) — Poignée de drag en haut du panneau ASK. Tirer vers le haut = panneau plus grand (graphe plus petit), vers le bas = l'inverse. Limites min 100px, max 80% du conteneur. Barre verte au survol, body scrollable indépendant.
- **Export HTML de la réponse** (`ask.js`) — Bouton "📥 Export HTML" affiché après chaque réponse. Génère un fichier HTML autonome avec CSS inline, branding Cloud Temple, question posée, réponse formatée Markdown (tableaux, code, blockquotes), entités identifiées, documents sources. Compatible impression (`@media print`). Nommé `graph-memory-YYYY-MM-DD-HHmm.html`.
- **Barre d'actions unifiée** (`ask.js`, `graph.css`) — Les boutons "🔬 Isoler le sujet" et "📥 Export HTML" sont regroupés dans un conteneur `ask-actions` sous la réponse.

#### Corrigé
- **Toggle Documents inefficace en mode isolation** (`config.js`) — En mode Focus (après "🔬 Isoler le sujet"), les nœuds Document étaient dans `filterState.isolatedNodes`, et le `return true` de l'isolation court-circuitait le test `showMentions`. Les carrés rouges restaient visibles même avec le toggle OFF. Corrigé en plaçant le test `showMentions` **avant** le test d'isolation.

#### Fichiers modifiés
`config.js`, `ask.js`, `graph.css`, `graph.html`

---

## [0.6.3] — 2026-02-15

### Recherche accent-insensitive + Calibrage seuil RAG

#### Ajouté
- **Index fulltext Neo4j `standard-folding`** (`graph.py`) — Recherche accent-insensitive via un index Lucene avec ASCII folding (é→e, ç→c, ü→u). `"réversibilité"`, `"reversibilite"`, `"REVERSIBILITE"` matchent tous les 3. Lazy init idempotent au premier appel de `search_entities()`.
- **`_search_fulltext()`** — Recherche principale via l'index Lucene avec scoring par pertinence, filtrée par `memory_id`.
- **`_search_contains()` amélioré** — Fallback CONTAINS qui envoie les tokens raw (avec accents) ET normalisés (sans accents) à Neo4j.
- **`_escape_lucene()`** — Échappement des caractères spéciaux Lucene (`+`, `-`, `*`, `?`, `~`, etc.).

#### Corrigé
- **Recherche "réversibilité" → 0 résultats** — Python normalisait les accents (`reversibilite`) mais `toLower()` de Neo4j les conservait (`réversibilité`). Désalignement corrigé par l'index fulltext `standard-folding` (principal) + fallback CONTAINS avec double tokens.
- **RAG quasi inactif (seuil 0.65 trop élevé)** — BGE-M3 produit des scores cosinus ~0.55-0.63 pour les meilleurs chunks. Le seuil 0.65 éliminait 93% des chunks pertinents. Abaissé à **0.58** après benchmark comparatif sur 5 questions × 5 seuils (`scripts/test_rag_thresholds.py`).

#### Modifié
- **`RAG_SCORE_THRESHOLD` 0.65 → 0.58** — Calibré pour BGE-M3 via benchmark (0.50/0.55/0.58/0.60/0.65 testés sur 5 requêtes × 15 chunks).

#### Refactorisé
- **`search_entities()`** — Stratégie en 2 niveaux : fulltext Lucene (scoring) → fallback CONTAINS (raw+normalized). 3 nouvelles méthodes privées.

#### Fichiers modifiés
`graph.py`, `config.py`, `.env.example`, `README.md`

---

## [0.6.2] — 2026-02-15

### Interface web graphe améliorée + Progression CLI

#### Ajouté
- **Toggle MENTIONS** (📄) — Nouveau bouton toggle dans le header du client web pour masquer/afficher les nœuds Document et les arêtes MENTIONS. Permet de visualiser uniquement les relations sémantiques entre entités (`displayOptions.showMentions` dans `config.js`).
- **Progression CLI avec barres %** — L'ingestion en ligne de commande affiche des barres de progression ASCII pour l'extraction LLM (chunk par chunk) et l'embedding (batch par batch), avec compteur d'entités/relations en temps réel.

#### Corrigé
- **Exit isolation automatique avant ASK** — Quand l'utilisateur pose une nouvelle question alors que le mode Focus est actif, le graphe repasse automatiquement en vue globale. Plus de filtrage résiduel entre deux questions.

#### Fichiers modifiés
`config.js`, `graph.html`, `app.js`, `ask.js`, `commands.py`

---

## [0.6.1] — 2026-02-15

### Stabilisation ingestion gros documents + Observabilité

#### Corrigé
- **Boucle infinie chunker** (`chunker.py`) — `_split_group_with_overlap()` pouvait boucler infiniment quand overlap + prochaine phrase dépassait `chunk_size` → millions de chunks → 7.47GB RAM → OOM Kill (exit 137). Corrigé en vidant l'overlap si nécessaire.
- **Healthcheck Docker OOM** (`Dockerfile`) — Remplacé `python -c "import httpx; ..."` par `curl` (économise ~50MB RAM par check toutes les 30s).

#### Modifié
- **`EXTRACTION_CHUNK_SIZE` réduit** (`config.py`) — 200K → **25K chars** (~6K tokens par chunk). Un document de 135K chars → 7 chunks au lieu de 1.

#### Ajouté
- **Libération mémoire proactive** (`server.py`) — `del content_base64` + `del content` + `gc.collect()`. Monitoring RSS dans chaque log `[RSS=XXmb]`.
- **Logs chunker détaillés** (`chunker.py`) — 3 passes avec détail section par section (titre, chars, level). `sys.stderr.flush()` systématique.
- **Progression CLI temps réel** (`client.py` + `commands.py`) — Notifications MCP `ctx.info()` capturées côté client via monkey-patch `_received_notification`. Rich Live display avec étapes + timer.
- **Déduplication vérifiée** — Deux niveaux : extracteur (`_merge_extraction_results` : par nom+type) + Neo4j (`MERGE` Cypher sur `{name, memory_id}`).

#### Fichiers modifiés
`chunker.py`, `Dockerfile`, `config.py`, `server.py`, `client.py`, `commands.py`

---

## [0.6.0] — 2026-02-13

### Chunked Graph Extraction + Métadonnées enrichies

#### Ajouté
- **Extraction chunked séquentielle** (`extractor.py`) — Documents longs découpés en chunks extraits séquentiellement avec contexte cumulatif. Fusion finale avec déduplication par (nom, type).
- **Métadonnées enrichies** — Nœud Document Neo4j : `source_path`, `source_modified_at`, `size_bytes`, `text_length`, `content_type`.
- **`document_get` optimisé** — Paramètre `include_content=False` (défaut), pas de téléchargement S3 pour les métadonnées.
- **CLI enrichi** — `document ingest --source-path`, `document ingest-dir` passent automatiquement les métadonnées.
- **Paramètre** `EXTRACTION_CHUNK_SIZE` (défaut 200K chars, configurable via `.env`).
- **Documentation** — `DESIGN/chunking_methodology.md`.

#### Modifié
- **Timeout LLM** — 120s → **600s** (gpt-oss:120b chain-of-thought).
- **Résilience** — Si un chunk d'extraction timeout, l'ingestion continue avec les suivants.

#### Fichiers modifiés
`extractor.py`, `ontology.py`, `graph.py`, `server.py`, `config.py`, `commands.py`, `shell.py`, `.env.example`

---

## [0.5.2] — 2026-02-09

### Q&A — Fallback RAG-only + Tokeniser robuste

#### Corrigé
- **Tokeniser de recherche** (`graph.py`) — Ponctuation retirée avec `re.findall(r'[a-zA-ZÀ-ÿ]+', ...)`.
- **Normalisation des accents** — `unicodedata.normalize('NFKD', ...)` pour matcher `"résiliation"` ↔ `"RESILIATION"`.

#### Ajouté
- **Fallback RAG-only** — 0 entités graphe → recherche Qdrant sur tous les chunks (au lieu de "pas d'infos").
- **Seuil de pertinence RAG** (`RAG_SCORE_THRESHOLD=0.65`).
- **Limite de chunks configurable** (`RAG_CHUNK_LIMIT=8`).
- **Logs décisionnels Q&A** — Tokenisation → Graphe → RAG → Contexte LLM.
- **Scores de similarité** dans les logs Docker.
- **Stop words enrichis** (~45 mots français).
- **Modules RAG** — `chunker.py`, `embedder.py`, `vector_store.py`.

#### Modifié
- **Qdrant épinglé** `v1.16.2` (au lieu de `latest`).

#### Fichiers modifiés
`graph.py`, `server.py`, `config.py`, `docker-compose.yml`, `.env.example`, `chunker.py`, `embedder.py`, `vector_store.py`, `models.py`, `requirements.txt`

---

## [0.5.1] — 2026-02-09

### Tokens — Champ email + Hash complet

#### Ajouté
- Champ **email** (optionnel) lors de la création de tokens.
- **Hash complet** (SHA256, 64 chars) dans `token list`.
- Colonne **Email** dans les tables CLI + Shell.
- Fichier `VERSION`.
- Documentation CLI (`scripts/README.md`).

#### Fichiers modifiés
`models.py`, `token_manager.py`, `server.py`, `display.py`, `commands.py`, `shell.py`

---

## [0.5.0] — 2026-02-01

### Version initiale publique

#### Ajouté
- Extraction d'entités/relations guidée par ontologie (LLM).
- Graphe de connaissances Neo4j avec isolation par namespace (multi-tenant).
- Stockage S3 (Dell ECS, AWS, MinIO).
- Interface web interactive (vis-network) avec filtrage avancé et panneau ASK.
- CLI complète (Click + Shell interactif avec prompt_toolkit).
- Authentification Bearer Token avec gestion des tokens.
- Vérification et nettoyage cohérence S3/graphe.
- Question/Réponse avec citation des documents sources.
- 14 outils MCP exposés via HTTP/SSE.
- Support des formats : PDF, DOCX, Markdown, TXT, HTML, CSV.
- 4 ontologies : legal, cloud, managed-services, technical.
