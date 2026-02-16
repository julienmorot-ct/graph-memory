# 🔒 Analyse de Risques Sécurité — Graph Memory v1.0.0

> **Date** : 16 février 2026  
> **Auteur** : Cloud Temple — Direction Technique  
> **Version** : 1.0  
> **Statut** : Validé  

---

## 1. Périmètre

Ce document analyse les risques de sécurité de l'architecture Graph Memory v1.0.0, avec un focus sur :

- L'architecture réseau (WAF Coraza, réseau Docker isolé)
- Le routage différencié (routes avec/sans WAF)
- Les protections applicatives (authentification, validation, paramétrage)
- Les vecteurs d'attaque résiduels et les mesures de mitigation

---

## 2. Architecture de sécurité

### 2.1 Vue d'ensemble

```
Internet / Réseau local
         │
         ▼ Port 8080 (seul port exposé)
┌─────────────────────────────────────────────────┐
│         Coraza WAF (Caddy + OWASP CRS)          │
│                                                   │
│  /sse*        ──► Reverse Proxy DIRECT ──────┐   │
│  /messages/*  ──► Reverse Proxy DIRECT ──────┤   │
│  /api/*       ──► WAF CRS ► Reverse Proxy ──┤   │
│  /*           ──► WAF CRS ► Reverse Proxy ──┤   │
│                                               │   │
│  Headers sécurité sur TOUTES les routes       │   │
└───────────────────────────────────────────────┼───┘
         Réseau Docker interne (mcp-network)    │
         │              │              │        │
         ▼              ▼              ▼        ▼
    ┌─────────┐   ┌──────────┐   ┌────────────────┐
    │ Neo4j 5 │   │  Qdrant  │   │  MCP Memory    │
    │ (7687)  │   │  (6333)  │   │  (8002)        │
    │         │   │          │   │  AuthMiddleware │
    │ NON     │   │  NON     │   │  + Pydantic    │
    │ EXPOSÉ  │   │  EXPOSÉ  │   │  + Bearer Token│
    └─────────┘   └──────────┘   └────────────────┘
```

### 2.2 Couches de défense

| Couche                    | Technologie                                    | Portée                                            |
| ------------------------- | ---------------------------------------------- | ------------------------------------------------- |
| **L1 — Réseau**           | Docker network isolé, seul port 8080 exposé    | Neo4j, Qdrant, MCP inaccessibles de l'extérieur   |
| **L2 — WAF**              | Coraza + OWASP CRS                             | Routes `/api/*`, `/health`, `/graph`, `/static/*` |
| **L3 — Headers HTTP**     | CSP, X-Frame-Options, nosniff, Referrer-Policy | Toutes les routes (y compris SSE/messages)        |
| **L4 — Authentification** | Bearer Token (middleware ASGI)                 | `/sse`, `/messages/*`, `/api/*`                   |
| **L5 — Validation**       | Pydantic models, FastMCP schema                | Tous les outils MCP via `/messages`               |
| **L6 — Paramétrage BDD**  | Paramètres liés Cypher (`$params`)             | Toutes les requêtes Neo4j                         |
| **L7 — Container**        | `USER mcp` (non-root)                          | Processus MCP                                     |

---

## 3. Matrice de risques par route

### 3.1 Route `/sse*` — SANS WAF

| Critère               | Valeur                                                |
| --------------------- | ----------------------------------------------------- |
| **Méthode HTTP**      | GET (lecture seule)                                   |
| **Body requête**      | Aucun                                                 |
| **Authentification**  | Bearer Token obligatoire (L4)                         |
| **Durée connexion**   | Longue (heures) — SSE streaming                       |
| **Raison bypass WAF** | Coraza bufférise les réponses → incompatible avec SSE |

#### Vecteurs d'attaque

| Vecteur                    | Probabilité | Impact | Risque          | Mitigation                                         |
| -------------------------- | ----------- | ------ | --------------- | -------------------------------------------------- |
| Accès non autorisé         | Faible      | Moyen  | **Faible**      | Token Bearer obligatoire (L4)                      |
| Injection via headers      | Très faible | Faible | **Négligeable** | Pas de traitement des headers customs côté serveur |
| DoS (connexions multiples) | Moyen       | Moyen  | **Moyen**       | Headers sécurité (L3), timeout Caddy par défaut    |
| Interception du flux       | Moyen       | Élevé  | **Moyen**       | TLS en production (Let's Encrypt)                  |
| Injection via query string | Très faible | Faible | **Négligeable** | Le session_id est un UUID généré côté serveur      |

**Risque global : 🟢 FAIBLE**

> Le flux SSE est en lecture seule (serveur → client). L'unique paramètre est le `session_id` dans l'URL, qui est un UUID généré par le serveur. Aucun body, aucun paramètre utilisateur traité.

---

### 3.2 Route `/messages/*` — SANS WAF

| Critère               | Valeur                                                      |
| --------------------- | ----------------------------------------------------------- |
| **Méthode HTTP**      | POST                                                        |
| **Body requête**      | JSON MCP (paramètres d'outils, base64 de documents)         |
| **Authentification**  | Bearer Token obligatoire (L4)                               |
| **Durée requête**     | Jusqu'à 30 min (ingestion avec extraction LLM)              |
| **Raison bypass WAF** | Body base64 volumineux → faux positifs CRS ; timeouts longs |

#### Vecteurs d'attaque

| Vecteur                   | Probabilité | Impact   | Risque          | Mitigation                                                                                                     |
| ------------------------- | ----------- | -------- | --------------- | -------------------------------------------------------------------------------------------------------------- |
| Accès non autorisé        | Faible      | Élevé    | **Moyen**       | Token Bearer obligatoire (L4)                                                                                  |
| Injection Cypher (Neo4j)  | Très faible | Critique | **Faible**      | Paramètres liés `$params` dans TOUTES les requêtes Cypher (L6). Jamais de concaténation de strings.            |
| Injection SQL             | N/A         | N/A      | **Nul**         | Pas de base SQL (Neo4j uniquement)                                                                             |
| XSS dans les paramètres   | Faible      | Faible   | **Négligeable** | Les réponses sont du JSON, pas du HTML rendu. Le CSP (L3) protège le navigateur.                               |
| Path traversal (filename) | Faible      | Moyen    | **Faible**      | Validation côté serveur : le filename est utilisé comme clé S3, pas comme chemin filesystem                    |
| Prompt injection (LLM)    | Moyen       | Moyen    | **Moyen**       | Inhérent à tout système RAG/LLM. Le contenu est passé comme contexte, pas comme instruction système.           |
| DoS (gros payload)        | Faible      | Moyen    | **Faible**      | `MAX_DOCUMENT_SIZE_MB=50`, `SecRequestBodyLimit=75MB` (CRS implicite sur la route WAF), timeout 1800s          |
| Exfiltration de données   | Faible      | Élevé    | **Moyen**       | Token Bearer avec permissions granulaires (`memory_ids`). Un token ne peut accéder qu'aux mémoires autorisées. |
| Base64 malveillant        | Très faible | Faible   | **Négligeable** | Le base64 est décodé → parsé (PDF/DOCX/MD) → texte brut → envoyé au LLM. Pas d'exécution de code.              |

**Risque global : 🟡 MOYEN-FAIBLE**

> La route `/messages` est la plus exposée car elle reçoit des données utilisateur en POST. Cependant, l'attaquant doit posséder un **token valide** (pas d'accès anonyme). Les protections applicatives (paramètres liés Cypher, validation Pydantic, limites de taille) couvrent les principaux vecteurs d'injection. Le risque résiduel principal est la prompt injection LLM, qui est inhérent à tout système RAG.

---

### 3.3 Routes `/api/*` — AVEC WAF

| Critère              | Valeur                             |
| -------------------- | ---------------------------------- |
| **Méthodes HTTP**    | GET, POST                          |
| **Body requête**     | JSON (question, query, memory_id)  |
| **Authentification** | Bearer Token obligatoire (L4)      |
| **Protection WAF**   | Coraza + OWASP CRS (L2)            |
| **Headers sécurité** | CSP, X-Frame-Options, nosniff (L3) |

#### Vecteurs d'attaque

| Vecteur              | Probabilité | Impact   | Risque          | Mitigation                                        |
| -------------------- | ----------- | -------- | --------------- | ------------------------------------------------- |
| Injection SQL/Cypher | Très faible | Critique | **Très faible** | WAF CRS (L2) + paramètres liés (L6)               |
| XSS                  | Très faible | Moyen    | **Très faible** | WAF CRS (L2) + CSP (L3) + réponses JSON           |
| SSRF                 | Très faible | Élevé    | **Très faible** | WAF CRS (L2) + pas de fetch d'URL utilisateur     |
| Path traversal       | Très faible | Moyen    | **Très faible** | WAF CRS (L2) + pas d'accès filesystem direct      |
| Brute force token    | Faible      | Élevé    | **Faible**      | WAF CRS scanner detection + tokens longs (SHA256) |

**Risque global : 🟢 TRÈS FAIBLE**

---

### 3.4 Routes publiques (`/health`, `/graph`, `/static/*`) — AVEC WAF, SANS AUTH

| Critère              | Valeur                             |
| -------------------- | ---------------------------------- |
| **Authentification** | Aucune (public)                    |
| **Protection WAF**   | Coraza + OWASP CRS (L2)            |
| **Headers sécurité** | CSP, X-Frame-Options, nosniff (L3) |

#### Vecteurs d'attaque

| Vecteur                 | Probabilité | Impact | Risque          | Mitigation                                                        |
| ----------------------- | ----------- | ------ | --------------- | ----------------------------------------------------------------- |
| Reconnaissance (health) | Élevé       | Faible | **Faible**      | `/health` ne divulgue que version + status Neo4j                  |
| XSS via interface web   | Faible      | Moyen  | **Très faible** | WAF CRS (L2) + CSP strict (L3) + pas d'input utilisateur persisté |
| Clickjacking            | Très faible | Faible | **Négligeable** | `X-Frame-Options: DENY` + `frame-ancestors 'none'`                |
| Information disclosure  | Faible      | Faible | **Faible**      | Headers `-Server` `-X-Powered-By` supprimés                       |

**Risque global : 🟢 TRÈS FAIBLE**

---

## 4. Synthèse des risques

| Route                          | WAF | Auth | Risque global    | Justification                                         |
| ------------------------------ | --- | ---- | ---------------- | ----------------------------------------------------- |
| `/sse*`                        | ❌  | ✅   | 🟢 Faible       | GET lecture seule, aucun input utilisateur            |
| `/messages/*`                  | ❌  | ✅   | 🟡 Moyen-Faible | POST avec données, mais auth + validation applicative |
| `/api/*`                       | ✅  | ✅   | 🟢 Très faible  | Double protection WAF + applicative                   |
| `/health`, `/graph`, `/static` | ✅  | ❌   | 🟢 Très faible  | Contenu statique, pas de données sensibles            |

---

## 5. Risques transversaux

### 5.1 Prompt Injection (LLM)

|                       |                                                                                                                                                                                                       |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Probabilité**       | Moyenne                                                                                                                                                                                               |
| **Impact**            | Moyen (réponse biaisée, extraction d'instructions système)                                                                                                                                            |
| **Routes concernées** | `/messages/*` (tool `question_answer`, `memory_ingest`), `/api/ask`                                                                                                                                   |
| **Mitigation**        | Le contenu utilisateur est injecté comme **contexte** (pas comme instruction système). Le prompt système est séparé et non modifiable. Risque inhérent à tout système RAG — pas de solution parfaite. |
| **Risque résiduel**   | 🟡 Accepté — inhérent à l'usage d'un LLM                                                                                                                                                             |

### 5.2 Token compromise

|                       |                                                                                                                                                                                        |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Probabilité**       | Faible                                                                                                                                                                                 |
| **Impact**            | Élevé (accès aux données de la mémoire)                                                                                                                                                |
| **Routes concernées** | Toutes les routes authentifiées                                                                                                                                                        |
| **Mitigation**        | Tokens avec permissions granulaires (`memory_ids`). Révocation immédiate via `admin_revoke_token`. Expiration configurable. Hash SHA256 (pas de stockage en clair). TLS en production. |
| **Risque résiduel**   | 🟡 Acceptable — bonnes pratiques de gestion des tokens                                                                                                                                |

### 5.3 Denial of Service (DoS)

|                              |                                                                                                                                      |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| **Probabilité**              | Moyenne                                                                                                                              |
| **Impact**                   | Moyen (indisponibilité temporaire)                                                                                                   |
| **Routes concernées**        | Toutes                                                                                                                               |
| **Mitigation actuelle**      | Limites de taille (`MAX_DOCUMENT_SIZE_MB`, `SecRequestBodyLimit`), timeouts. WAF CRS scanner/bot detection sur les routes protégées. |
| **Amélioration recommandée** | ✅ **IMPLÉMENTÉ** : `caddy-ratelimit` avec 4 zones par IP (SSE 10/min, messages 60/min, API 30/min, global 200/min)                 |
| **Risque résiduel**          | � Faible — rate limiting actif sur toutes les routes                                                                                |

### 5.4 CSP avec `unsafe-inline`

|                              |                                                                                                                                                    |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Probabilité**              | Très faible                                                                                                                                        |
| **Impact**                   | Moyen (XSS si combiné avec une autre vulnérabilité)                                                                                                |
| **Routes concernées**        | `/graph` (interface web)                                                                                                                           |
| **Raison**                   | Le code JavaScript utilise des handlers `onclick=""` inline dans le HTML généré dynamiquement (bouton "Isoler le sujet", tags entités cliquables). |
| **Amélioration recommandée** | Refactorer le JS pour utiliser `addEventListener` au lieu de `onclick` inline → permettrait de supprimer `'unsafe-inline'` du CSP `script-src`.    |
| **Risque résiduel**          | 🟢 Faible — XSS nécessiterait une vulnérabilité d'injection préalable (bloquée par le WAF CRS)                                                    |

---

## 6. Recommandations d'amélioration

### Priorité haute 🔴

| #   | Recommandation                                                                           | Effort | Impact sécurité      |
| --- | ---------------------------------------------------------------------------------------- | ------ | -------------------- |
| 1   | ~~**Rate limiting**~~ ✅ **IMPLÉMENTÉ** v1.0.0 : `caddy-ratelimit` 4 zones (SSE 10/min, messages 60/min, API 30/min, global 200/min par IP) | ~~Faible~~ | ~~Élevé~~ |
| 2   | **TLS en production** — Configurer `SITE_ADDRESS=domaine.com` pour activer Let's Encrypt | Faible | Élevé (interception) |

### Priorité moyenne 🟡

| #   | Recommandation                                                                                  | Effort | Impact sécurité          |
| --- | ----------------------------------------------------------------------------------------------- | ------ | ------------------------ |
| 3   | **Supprimer `unsafe-inline`** — Refactorer les `onclick` en `addEventListener`                  | Moyen  | Moyen (CSP strict)       |
| 4   | **Logging des accès `/messages`** — Logger les appels d'outils MCP avec IP source et token hash | Faible | Moyen (traçabilité)      |
| 5   | **Rotation des tokens** — Expiration automatique + renouvellement                               | Moyen  | Moyen (token compromise) |

### Priorité basse 🟢

| #   | Recommandation                                                                                                                            | Effort | Impact sécurité        |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------ | ---------------------- |
| 6   | **WAF personnalisé pour `/messages`** — Règles Coraza custom (pas le CRS complet) pour inspecter la structure JSON MCP sans faux positifs | Élevé  | Faible (gain marginal) |
| 7   | **HSTS** — Ajouter `Strict-Transport-Security` quand TLS est activé                                                                       | Faible | Faible (déjà TLS)      |
| 8   | **Audit log Neo4j** — Activer les logs d'audit Neo4j Enterprise                                                                           | Élevé  | Faible (forensics)     |

---

## 7. Décision d'architecture : pourquoi `/sse` et `/messages` sans WAF ?

### Contrainte technique

Coraza WAF bufférise **intégralement** les réponses HTTP pour les inspecter (outbound rules). Ce comportement est incompatible avec :

1. **SSE** (`/sse`) — Le flux reste ouvert pendant des heures. Coraza attend la fin de la réponse pour l'inspecter → le client ne reçoit jamais les événements.
2. **Ingestion longue** (`/messages`) — L'extraction LLM + vectorisation peut prendre 15-30 minutes. Avec le CRS, le body JSON contenant du base64 de documents (parfois 50 MB) déclenche systématiquement des faux positifs :
   - Règle 942100 (SQL injection) — le base64 contient des patterns `SELECT`, `UNION`, `FROM`
   - Règle 941100 (XSS) — le base64 contient des patterns `<script>`, `onclick`
   - Règle 920420 (Request body too large) — base64 de 50 MB

### Alternatives évaluées et rejetées

| Alternative                                      | Raison du rejet                                                       |
| ------------------------------------------------ | --------------------------------------------------------------------- |
| Coraza avec `responseBodyAccess=Off`             | Le buffering se produit quand même — le middleware intercepte le flux |
| Exclusions CRS par règle                         | Trop de règles à exclure (20+), fragilise la protection globale       |
| WAF en mode détection uniquement sur `/messages` | Complexe à configurer par route, gain marginal                        |
| Caddy sans Coraza (juste reverse proxy)          | Perd toute la protection OWASP Top 10 sur les routes web              |

### Conclusion

Le bypass WAF sur 2 routes est un **compromis pragmatique et justifié** :
- Les routes bypassées sont **authentifiées** (Bearer Token)
- Les protections applicatives (Pydantic, paramètres liés Cypher) sont **solides**
- Le WAF protège les routes les plus **exposées** (interface web publique, API REST)
- Le risque résiduel est **acceptable** pour un service interne/entreprise

---

## 8. Conformité

| Exigence                       | Statut | Détail                                                                                                                                                                                      |
| ------------------------------ | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OWASP Top 10 — Injection       | ✅     | WAF CRS + paramètres liés Cypher                                                                                                                                                            |
| OWASP Top 10 — Broken Auth     | ✅     | Bearer Token + bootstrap key + révocation                                                                                                                                                   |
| OWASP Top 10 — Sensitive Data  | ✅     | TLS en prod, réseau Docker isolé                                                                                                                                                            |
| OWASP Top 10 — XSS             | ✅     | WAF CRS + CSP + X-Content-Type-Options                                                                                                                                                      |
| OWASP Top 10 — Insecure Config | ✅     | Container non-root, ports non exposés, admin off                                                                                                                                            |
| OWASP Top 10 — SSRF            | ✅     | WAF CRS + pas de fetch d'URL utilisateur                                                                                                                                                    |
| SecNumCloud (réseau)           | ✅     | Isolation réseau, chiffrement TLS, WAF                                                                                                                                                      |
| RGPD (données personnelles)    | ⚠️   | Les documents ingérés peuvent contenir des données personnelles. Isolation par mémoire (`memory_id`). Suppression cascade (document + entités). Pas de rétention au-delà de la suppression. |

---

*Document généré le 16 février 2026 — Graph Memory v1.0.0*
