/**
 * MCP Memory - Rendu vis-network, détails de nœuds, isolation de sous-graphe
 *
 * renderGraph() reçoit des nœuds/arêtes DÉJÀ FILTRÉS par applyFilters() (config.js).
 * Il ne fait plus de filtrage interne — il rend ce qu'on lui donne.
 */

/** Rend le graphe dans le conteneur #graph */
function renderGraph(nodes, edges) {
    const container = document.getElementById('graph');
    const isIsolated = filterState.isolatedNodes !== null;

    const visNodes = nodes.map(n => {
        const bgColor = TYPE_COLORS[n.type] || TYPE_COLORS.Unknown;
        const base = currentParams.nodeSize;

        // Label complet, sans troncature
        const label = n.label;

        // En mode isolation, les documents sont plus gros et en forme d'icône
        const docSizeMultiplier = isIsolated ? 2.2 : 1.5;

        return {
            id: n.id, label,
            title: `${n.label}\n━━━━━━━━━━━━━━\nType: ${n.type}\n${n.description || ''}`,
            color: {
                background: bgColor, border: bgColor,
                highlight: { background: '#fff', border: bgColor },
                hover: { background: bgColor, border: '#fff' }
            },
            font: {
                color: '#fff', size: currentParams.fontSize, face: 'Arial',
                strokeWidth: 2, strokeColor: '#000'
            },
            size: n.node_type === 'document' ? base * docSizeMultiplier : base + Math.min(n.mentions || 0, 10) * 2,
            shape: n.node_type === 'document' ? 'square' : 'dot',
            borderWidth: (isIsolated && n.node_type === 'document') ? 3 : 2,
            data: n
        };
    });

    const showLabels = true; // Labels toujours visibles (simplifié)
    const visEdges = edges.map((e, i) => {
        const isMentions = e.type === 'MENTIONS';
        return {
            id: i, from: e.from, to: e.to,
            label: (isIsolated && isMentions) ? '' : (showLabels ? (e.type || '').replace(/_/g, ' ') : ''),
            title: `${e.type}\n${e.description || ''}`,
            arrows: { to: { enabled: true, scaleFactor: 0.5 } },
            color: { color: EDGE_COLORS[e.type] || '#556', highlight: '#fff', hover: '#aaa' },
            font: { color: '#bbb', size: Math.max(currentParams.fontSize - 2, 8), strokeWidth: 2, strokeColor: '#000', align: 'top' },
            width: isMentions ? 1 : 2,
            dashes: (isIsolated && isMentions) ? [5, 5] : false,
            smooth: { type: 'continuous', roundness: 0.2 }
        };
    });

    const data = { nodes: new vis.DataSet(visNodes), edges: new vis.DataSet(visEdges) };

    const options = {
        physics: {
            enabled: true,
            barnesHut: {
                gravitationalConstant: -currentParams.gravity, centralGravity: 0.1,
                springLength: currentParams.springLength, springConstant: 0.02,
                damping: 0.9, avoidOverlap: 0.5
            },
            stabilization: { iterations: 300, fit: true }, maxVelocity: 30, minVelocity: 0.75
        },
        interaction: { hover: true, tooltipDelay: 100, zoomView: true, dragView: true, navigationButtons: true, keyboard: true },
        nodes: { borderWidth: 2, shadow: { enabled: true, size: 5 } },
        edges: { width: 1.5, selectionWidth: 3, shadow: false },
        layout: { improvedLayout: true }
    };

    appState.network = new vis.Network(container, data, options);

    // Geler après stabilisation
    appState.network.on('stabilizationIterationsDone', function () {
        appState.network.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
        setTimeout(() => appState.network.setOptions({ physics: { enabled: false } }), 600);
    });
    appState.network.on('dragStart', () => appState.network.setOptions({ physics: { enabled: true, stabilization: false } }));
    appState.network.on('dragEnd', () => setTimeout(() => appState.network.setOptions({ physics: { enabled: false } }), 1000));

    // Clic nœud → détails
    appState.network.on('click', function (params) {
        if (params.nodes.length > 0) {
            const node = appState.currentData.nodes.find(n => n.id === params.nodes[0]);
            if (node) showNodeDetails(node);
        } else {
            hideNodeDetails();
        }
    });
}

/** Affiche les détails riches d'un nœud */
function showNodeDetails(node) {
    const details = document.getElementById('nodeDetails');
    const content = document.getElementById('detailContent');
    const color = TYPE_COLORS[node.type] || TYPE_COLORS.Unknown;
    const data = appState.currentData;

    const connectedEdges = data ? data.edges.filter(e => (e.from === node.id || e.to === node.id) && e.type !== 'MENTIONS') : [];
    const sourceDocs = (node.source_docs || []).map(docId => {
        const doc = data ? data.documents.find(d => d.id === docId) : null;
        return doc ? doc.filename : docId;
    });

    let html = `<h4>${node.label}</h4>
        <span class="type-badge" style="background:${color}">${node.type}</span>
        ${node.mentions > 1 ? `<span style="font-size:0.7rem;color:#4CAF50;margin-left:0.3rem">×${node.mentions}</span>` : ''}`;

    if (node.description) {
        const descriptions = node.description.split(' | ');
        html += `<div class="detail-section"><div class="detail-label">📝 Description</div>
            ${descriptions.map(d => `<p>${d.trim()}</p>`).join('')}</div>`;
    }
    if (sourceDocs.length > 0) {
        html += `<div class="detail-section"><div class="detail-label">📄 Documents (${sourceDocs.length})</div>
            <div>${sourceDocs.map(d => `<span class="doc-tag">📄 ${d}</span>`).join('')}</div></div>`;
    }
    if (connectedEdges.length > 0) {
        html += `<div class="detail-section"><div class="detail-label">🔗 Relations (${connectedEdges.length})</div>`;
        connectedEdges.slice(0, 15).forEach(e => {
            const other = e.from === node.id ? e.to : e.from;
            const dir = e.from === node.id ? '→' : '←';
            html += `<div class="relation-item" style="cursor:pointer" onclick="focusNode('${other}')">
                <span class="relation-type">${(e.type || 'RELATED').replace(/_/g, ' ')}</span>
                <span>${dir} ${other.length > 28 ? other.substring(0, 26) + '…' : other}</span></div>`;
        });
        if (connectedEdges.length > 15) html += `<p style="font-size:0.7rem;color:#888">… +${connectedEdges.length - 15}</p>`;
        html += `</div>`;
    }

    content.innerHTML = html;
    details.classList.add('visible');
}

function hideNodeDetails() {
    document.getElementById('nodeDetails').classList.remove('visible');
}

/** Focus et sélection d'un nœud par ID */
function focusNode(nodeId) {
    if (appState.network) {
        appState.network.focus(nodeId, { scale: 1.5, animation: true });
        appState.network.selectNodes([nodeId]);
        const node = appState.currentData.nodes.find(n => n.id === nodeId);
        if (node) showNodeDetails(node);
    }
}

/**
 * Met en évidence des nœuds par nom (pour ASK).
 * Les nœuds matchés sont sélectionnés et zoomés.
 */
function highlightEntities(entityNames) {
    if (!appState.network || !appState.currentData) return;

    const namesLower = entityNames.map(n => n.toLowerCase());
    const matchingIds = appState.currentData.nodes
        .filter(n => namesLower.includes(n.label.toLowerCase()))
        .map(n => n.id);

    if (matchingIds.length > 0) {
        appState.network.selectNodes(matchingIds);
        if (matchingIds.length <= 5) {
            appState.network.fit({ nodes: matchingIds, animation: { duration: 600, easingFunction: 'easeInOutQuad' } });
        }
    }
}

/** Efface la mise en évidence */
function clearHighlight() {
    if (appState.network) appState.network.unselectAll();
}

// ═══════════════ MODE ISOLATION (FOCUS QUESTION) ═══════════════

/**
 * Isole le sous-graphe lié à une liste de noms d'entités.
 * Montre ces entités + leurs voisins directs (1 hop) + les documents sources
 * + les arêtes MENTIONS. Active la bannière "Mode Focus".
 *
 * @param {string[]} entityNames - Noms des entités à isoler (depuis la réponse ASK)
 */
function isolateSubgraph(entityNames) {
    if (!appState.currentData) return;

    const data = appState.currentData;
    const namesLower = entityNames.map(n => n.toLowerCase());

    // 1. Trouver les nœuds correspondants (entités de la réponse)
    const seedNodes = data.nodes.filter(n => namesLower.includes(n.label.toLowerCase()));
    const seedIds = new Set(seedNodes.map(n => n.id));

    if (seedIds.size === 0) return; // Rien à isoler

    // 2. Trouver les voisins directs (1 hop) via les arêtes
    const neighborIds = new Set(seedIds);
    data.edges.forEach(e => {
        if (seedIds.has(e.from)) neighborIds.add(e.to);
        if (seedIds.has(e.to)) neighborIds.add(e.from);
    });

    // 3. Inclure les nœuds Document sources de TOUTES les entités isolées
    //    (seeds + voisins) pour voir d'où vient chaque information
    const allIsolatedEntities = data.nodes.filter(n => neighborIds.has(n.id) && n.node_type !== 'document');
    allIsolatedEntities.forEach(entity => {
        if (entity.source_docs && entity.source_docs.length > 0) {
            entity.source_docs.forEach(docId => {
                // Vérifier que ce document existe dans les données
                const docNode = data.nodes.find(n => n.id === docId);
                if (docNode) neighborIds.add(docId);
            });
        }
    });

    // 4. S'assurer que MENTIONS est visible pour connecter docs ↔ entités
    filterState.visibleEdgeTypes.add('MENTIONS');
    // Mettre à jour la checkbox MENTIONS dans la sidebar si elle existe
    const mentionsCb = document.querySelector('#body-edgeTypes input[onchange*="MENTIONS"]');
    if (mentionsCb) mentionsCb.checked = true;
    const mentionsLabel = document.getElementById('label-etype-edge-MENTIONS');
    if (mentionsLabel) mentionsLabel.classList.remove('dimmed');

    // 5. Activer le mode isolation
    filterState.isolatedNodes = neighborIds;

    // 6. Afficher la bannière
    document.getElementById('isolationBanner').classList.add('visible');
    document.querySelector('.main').classList.add('with-banner');

    // 7. Appliquer les filtres (qui vont inclure l'isolation)
    applyFilters();

    // 8. Sélectionner les nœuds "seed" (les entités de la question)
    setTimeout(() => {
        if (appState.network) {
            appState.network.selectNodes([...seedIds]);
            appState.network.fit({
                nodes: [...neighborIds],
                animation: { duration: 600, easingFunction: 'easeInOutQuad' }
            });
        }
    }, 800);
}

/**
 * Quitte le mode isolation et restaure le graphe complet (avec filtres actuels).
 */
function exitIsolation() {
    filterState.isolatedNodes = null;

    // Masquer la bannière
    document.getElementById('isolationBanner').classList.remove('visible');
    document.querySelector('.main').classList.remove('with-banner');

    // Ré-appliquer les filtres sans isolation
    applyFilters();
}
