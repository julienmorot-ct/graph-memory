/**
 * MCP Memory - Orchestration et initialisation
 *
 * Point d'entrée : charge les mémoires, connecte les événements,
 * gère le chargement du graphe, la modale paramètres, et le mode isolation.
 */

/** Charge la liste des mémoires dans le select */
async function initMemories() {
    try {
        const result = await apiLoadMemories();
        const select = document.getElementById('memorySelect');
        if (result.status === 'ok') {
            result.memories.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.id;
                opt.textContent = `${m.id} — ${m.name}`;
                select.appendChild(opt);
            });
        }
    } catch (e) {
        console.error('Erreur chargement mémoires:', e);
    }
}

/** Charge le graphe de la mémoire sélectionnée */
async function loadSelectedGraph() {
    const memoryId = document.getElementById('memorySelect').value;
    if (!memoryId) return;

    const loading = document.getElementById('loading');
    loading.style.display = 'block';

    try {
        const result = await apiLoadGraph(memoryId);
        if (result.status !== 'ok') throw new Error(result.message);

        // Stocker les données brutes
        appState.currentData = result;
        appState.currentMemory = memoryId;

        // Initialiser l'état de filtrage (tout visible)
        initFilterState(result);

        // Construire les panneaux de filtrage dans la sidebar
        buildAllFilters(result);

        // Appliquer les filtres (= rendu initial complet)
        applyFilters();

        // Activer le bouton ASK
        document.getElementById('askBtn').disabled = false;

        // Quitter le mode isolation s'il était actif
        exitIsolation();

    } catch (e) {
        console.error('Erreur:', e);
        alert('Erreur: ' + e.message);
    } finally {
        loading.style.display = 'none';
    }
}

/** Setup des contrôles header */
function setupHeaderControls() {
    // Select mémoire → activer bouton Charger
    document.getElementById('memorySelect').addEventListener('change', function () {
        document.getElementById('loadBtn').disabled = !this.value;
    });
    document.getElementById('loadBtn').addEventListener('click', loadSelectedGraph);

    // Zoom to fit
    document.getElementById('fitBtn').addEventListener('click', () => {
        if (appState.network) appState.network.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
    });

    // Bouton "Graphe complet" (sortir du mode isolation)
    document.getElementById('exitIsolationBtn').addEventListener('click', exitIsolation);
}

/** Setup modale paramètres */
function setupSettingsModal() {
    const modal = document.getElementById('settingsModal');
    document.getElementById('settingsBtn').addEventListener('click', () => modal.classList.add('visible'));
    modal.addEventListener('click', e => { if (e.target === modal) modal.classList.remove('visible'); });

    // Sliders → affichage valeur
    const sliders = [
        { id: 'paramSpringLength', valId: 'valSpringLength', prefix: '' },
        { id: 'paramGravity', valId: 'valGravity', prefix: '-' },
        { id: 'paramNodeSize', valId: 'valNodeSize', prefix: '' },
        { id: 'paramFontSize', valId: 'valFontSize', prefix: '' }
    ];
    sliders.forEach(s => {
        document.getElementById(s.id).addEventListener('input', function () {
            document.getElementById(s.valId).textContent = s.prefix + this.value;
        });
    });

    // Reset
    document.getElementById('resetParams').addEventListener('click', () => {
        document.getElementById('paramSpringLength').value = DEFAULT_PARAMS.springLength;
        document.getElementById('paramGravity').value = DEFAULT_PARAMS.gravity;
        document.getElementById('paramNodeSize').value = DEFAULT_PARAMS.nodeSize;
        document.getElementById('paramFontSize').value = DEFAULT_PARAMS.fontSize;
        document.getElementById('valSpringLength').textContent = DEFAULT_PARAMS.springLength;
        document.getElementById('valGravity').textContent = '-' + DEFAULT_PARAMS.gravity;
        document.getElementById('valNodeSize').textContent = DEFAULT_PARAMS.nodeSize;
        document.getElementById('valFontSize').textContent = DEFAULT_PARAMS.fontSize;
    });

    // Appliquer
    document.getElementById('applyParams').addEventListener('click', () => {
        currentParams.springLength = parseInt(document.getElementById('paramSpringLength').value);
        currentParams.gravity = parseInt(document.getElementById('paramGravity').value);
        currentParams.nodeSize = parseInt(document.getElementById('paramNodeSize').value);
        currentParams.fontSize = parseInt(document.getElementById('paramFontSize').value);
        modal.classList.remove('visible');
        // Ré-appliquer les filtres avec les nouveaux paramètres de rendu
        applyFilters();
    });
}

/** Initialisation au chargement de la page */
document.addEventListener('DOMContentLoaded', () => {
    initMemories();
    setupHeaderControls();
    setupSettingsModal();
    setupSearchFilter();
    setupAsk();
});
