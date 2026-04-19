document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('toggle-monitor');
    const statusLabel = document.getElementById('status-label');
    const pulseDot = document.querySelector('.pulse-dot');
    
    const fieldsScannedEl = document.getElementById('fields-scanned');
    const risksFlaggedEl = document.getElementById('risks-flagged');

    // Load initial state
    chrome.storage.local.get(['isMonitoring', 'stats'], (result) => {
        const isMonitoring = result.isMonitoring !== false; // Default to true
        toggle.checked = isMonitoring;
        updateUIState(isMonitoring);
        
        if (result.stats) {
            fieldsScannedEl.innerText = result.stats.scanned || 0;
            risksFlaggedEl.innerText = result.stats.risks || 0;
        }
    });

    // Handle toggle
    toggle.addEventListener('change', (e) => {
        const isMonitoring = e.target.checked;
        chrome.storage.local.set({ isMonitoring });
        updateUIState(isMonitoring);
        
        // Notify background script
        chrome.runtime.sendMessage({ type: "TOGGLE_MONITOR", payload: isMonitoring });
    });

    function updateUIState(isMonitoring) {
        if (isMonitoring) {
            statusLabel.innerText = "Monitoring Active";
            statusLabel.classList.remove("inactive");
            pulseDot.style.animation = "pulse 2s infinite";
            pulseDot.style.backgroundColor = "var(--accent)";
        } else {
            statusLabel.innerText = "Monitoring Paused";
            statusLabel.classList.add("inactive");
            pulseDot.style.animation = "none";
            pulseDot.style.backgroundColor = "var(--text-muted)";
        }
    }

    // Listen for live stat updates from background worker
    chrome.runtime.onMessage.addListener((request) => {
        if (request.type === "STATS_UPDATE") {
            fieldsScannedEl.innerText = request.payload.scanned;
            risksFlaggedEl.innerText = request.payload.risks;
        }
    });
});
