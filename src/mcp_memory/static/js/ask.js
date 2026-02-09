/**
 * MCP Memory - Panneau ASK (question/réponse) avec highlight graphe
 * et mode "Focus Question" (isolation du sous-graphe pertinent).
 *
 * Après chaque réponse contenant des entités, un bouton "Isoler le sujet"
 * permet de filtrer le graphe pour ne montrer que le sous-graphe lié à la question.
 */

// Stocke les entités de la dernière réponse (pour le bouton Isoler)
let lastAnswerEntities = [];

/** Ouvre le panneau ASK */
function showAskPanel() {
    document.getElementById('askPanel').classList.add('visible');
    document.getElementById('askInput').focus();
}

/** Ferme le panneau ASK et efface la surbrillance */
function hideAskPanel() {
    document.getElementById('askPanel').classList.remove('visible');
    clearHighlight();
}

/** Soumet une question */
async function submitQuestion() {
    const input = document.getElementById('askInput');
    const question = input.value.trim();
    if (!question || !appState.currentMemory) return;

    const body = document.getElementById('askBody');
    const btn = document.getElementById('askSubmitBtn');

    // Afficher le loading
    body.innerHTML = '<div class="ask-loading"><div class="spinner" style="width:30px;height:30px;border-width:3px;margin:0 auto 0.5rem"></div>Réflexion en cours…</div>';
    btn.disabled = true;
    lastAnswerEntities = [];

    try {
        const result = await apiAsk(appState.currentMemory, question);

        if (result.status === 'ok') {
            displayAnswer(result);
            // Mettre en évidence les entités dans le graphe
            if (result.entities && result.entities.length > 0) {
                lastAnswerEntities = result.entities;
                highlightEntities(result.entities);
            }
        } else {
            body.innerHTML = `<div style="color:#e74c3c">❌ ${result.message || 'Erreur'}</div>`;
        }
    } catch (err) {
        body.innerHTML = `<div style="color:#e74c3c">❌ Erreur réseau: ${err.message}</div>`;
    } finally {
        btn.disabled = false;
    }
}

/** Affiche la réponse dans le panneau */
function displayAnswer(result) {
    const body = document.getElementById('askBody');

    // Convertir le markdown en HTML avec marked.js
    const answerHtml = marked.parse(result.answer || '', { breaks: true, gfm: true });

    let html = `<div class="ask-answer">${answerHtml}</div>`;

    // Entités trouvées (cliquables → focus dans le graphe)
    if (result.entities && result.entities.length > 0) {
        html += '<div class="ask-entities"><span style="font-size:0.72rem;color:#888;margin-right:0.3rem">🔗 Entités:</span>';
        result.entities.forEach(name => {
            html += `<span class="ask-entity-tag" onclick="focusNode('${escapeHtml(name)}')" title="Voir dans le graphe">${escapeHtml(name)}</span>`;
        });
        html += '</div>';

        // Bouton "Isoler le sujet" → mode Focus
        html += `<button class="ask-isolate-btn" onclick="isolateFromAsk()" title="Afficher uniquement le sous-graphe lié à cette question">
            🔬 Isoler le sujet dans le graphe
        </button>`;
    }

    // Documents sources (affichage en liste)
    if (result.source_documents && result.source_documents.length > 0) {
        html += `<div class="ask-sources">
            <div style="font-size:0.72rem;color:#888;margin-bottom:0.3rem">📄 Sources (${result.source_documents.length}):</div>`;
        result.source_documents.forEach(doc => {
            const name = doc.filename || doc.id || '?';
            html += `<div class="ask-source-item">📄 ${escapeHtml(name)}</div>`;
        });
        html += '</div>';
    }

    body.innerHTML = html;
}

/** Déclenche l'isolation du sous-graphe depuis le bouton dans le panneau ASK */
function isolateFromAsk() {
    if (lastAnswerEntities.length > 0) {
        isolateSubgraph(lastAnswerEntities);
    }
}

/** Échappe le HTML pour éviter les injections */
function escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

/** Setup des événements ASK */
function setupAsk() {
    // Bouton Ask dans le header
    document.getElementById('askBtn').addEventListener('click', showAskPanel);

    // Bouton submit
    document.getElementById('askSubmitBtn').addEventListener('click', submitQuestion);

    // Fermer
    document.getElementById('askCloseBtn').addEventListener('click', hideAskPanel);

    // Enter pour soumettre
    document.getElementById('askInput').addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submitQuestion();
        }
    });
}
