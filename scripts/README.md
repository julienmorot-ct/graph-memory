# Scripts de Test MCP Memory

Ce dossier contient des scripts de test pour valider le fonctionnement du serveur MCP Memory.

## Prérequis

1. **Serveur MCP Memory démarré** :
   ```bash
   docker compose up -d
   ```

2. **Dépendances Python installées** :
   ```bash
   pip install mcp python-dotenv
   ```

3. **Variables d'environnement** (optionnel) :
   - Le fichier `.env` à la racine du projet est automatiquement chargé
   - Vous pouvez aussi passer les options en ligne de commande

## Scripts disponibles

### 🏥 Test de Santé (`test_health.py`)

Vérifie que tous les services (S3, Neo4j, LLMaaS) sont connectés et fonctionnels.

```bash
python scripts/test_health.py
```

**Options** :
- `--url URL` : URL du serveur MCP (défaut: `http://localhost:8002`)
- `--token TOKEN` : Token d'authentification (défaut: valeur de `ADMIN_BOOTSTRAP_KEY`)

**Exemple** :
```bash
python scripts/test_health.py --url http://localhost:8002
```

---

### 🧪 Test du Workflow (`test_memory_workflow.py`)

Teste le workflow complet :
1. Création d'une mémoire
2. Ingestion d'un document (contrat de test)
3. Statistiques
4. Recherche dans le graphe
5. Récupération de contexte
6. Suppression de la mémoire

```bash
python scripts/test_memory_workflow.py
```

**Options** :
- `--url URL` : URL du serveur MCP
- `--token TOKEN` : Token d'authentification
- `--keep` : Ne pas supprimer la mémoire de test à la fin

**Exemples** :
```bash
# Test complet avec nettoyage
python scripts/test_memory_workflow.py

# Garder la mémoire pour inspection
python scripts/test_memory_workflow.py --keep
```

---

### 🔐 Test d'Authentification (`test_auth.py`)

Teste le système d'authentification :
1. Connexion avec clé bootstrap admin
2. Création de token client
3. Connexion avec le nouveau token
4. Liste des tokens
5. Tentative avec token invalide
6. Tentative sans token
7. Révocation de token

```bash
python scripts/test_auth.py
```

**Options** :
- `--url URL` : URL du serveur MCP
- `--token TOKEN` : Token admin bootstrap

---

## Codes de retour

| Code | Signification |
|------|---------------|
| 0 | Succès - Tous les tests passent |
| 1 | Échec - Un ou plusieurs tests ont échoué |
| 2 | Erreur - Pas de réponse du serveur |
| 3 | Erreur - Connexion refusée |
| 4 | Erreur - Exception inattendue |

---

## Exécution automatisée

Pour exécuter tous les tests :

```bash
#!/bin/bash
set -e

echo "=== Test de Santé ==="
python scripts/test_health.py

echo ""
echo "=== Test d'Authentification ==="
python scripts/test_auth.py

echo ""
echo "=== Test du Workflow ==="
python scripts/test_memory_workflow.py

echo ""
echo "✅ Tous les tests ont réussi!"
```

---

## Intégration CI/CD

Ces scripts retournent des codes de sortie standards et peuvent être utilisés dans des pipelines CI/CD :

```yaml
# Exemple GitHub Actions
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Start services
        run: docker compose up -d
      - name: Wait for services
        run: sleep 10
      - name: Run tests
        run: |
          pip install mcp python-dotenv
          python scripts/test_health.py
          python scripts/test_auth.py
          python scripts/test_memory_workflow.py
```

---

## Dépannage

### "Le package 'mcp' n'est pas installé"
```bash
pip install mcp
```

### "Impossible de se connecter"
Vérifiez que les conteneurs sont démarrés :
```bash
docker compose ps
docker compose logs mcp-memory
```

### Erreurs Pylance sur `.text`
Ces erreurs sont des faux positifs du type checker statique. Le code fonctionne correctement à l'exécution car nous manipulons toujours des `TextContent`.
