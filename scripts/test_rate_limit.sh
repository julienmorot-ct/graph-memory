#!/bin/bash
# Test du rate limiting WAF
# Usage: ./scripts/test_rate_limit.sh

TOKEN=$(grep ADMIN_BOOTSTRAP_KEY .env | cut -d= -f2)
URL="http://localhost:8080"

echo "=== Test rate limit /health (zone global: 200/min) ==="
for i in $(seq 1 5); do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/health")
    echo "  Req $i: HTTP $CODE"
done

echo ""
echo "=== Test burst /api/memories (zone api: 30/min) ==="
echo "    Envoi de 35 requêtes rapides..."
COUNT_200=0
COUNT_429=0
for i in $(seq 1 35); do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$URL/api/memories")
    if [ "$CODE" = "429" ]; then
        COUNT_429=$((COUNT_429 + 1))
    else
        COUNT_200=$((COUNT_200 + 1))
    fi
    echo "  Req $i: HTTP $CODE"
done

echo ""
echo "=== Résultat ==="
echo "  Requêtes OK (2xx): $COUNT_200"
echo "  Requêtes bloquées (429): $COUNT_429"

if [ "$COUNT_429" -gt 0 ]; then
    echo "  ✅ Rate limiting actif !"
else
    echo "  ⚠️  Aucune requête bloquée — vérifier la configuration"
fi
