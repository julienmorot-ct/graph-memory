# Changelog

Toutes les modifications notables de ce projet sont documentées dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/),
et ce projet adhère au [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
