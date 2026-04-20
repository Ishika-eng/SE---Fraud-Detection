console.log("FraudGuard Background Service Worker Started.");

// Must match API_KEY in backend .env — provisioned at extension deployment time
const API_KEY = "dev-key-change-in-production";

let stats = { scanned: 0, risks: 0 };
let isMonitoring = true;

// Initialize state
chrome.storage.local.get(['stats', 'isMonitoring'], (result) => {
    if (result.stats) stats = result.stats;
    if (result.isMonitoring !== undefined) isMonitoring = result.isMonitoring;
});

// Broadcast stats to popup
function broadcastStats() {
    chrome.storage.local.set({ stats });
    chrome.runtime.sendMessage({ type: "STATS_UPDATE", payload: stats }).catch(() => {});
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    
    // Handle toggle
    if (request.type === "TOGGLE_MONITOR") {
        isMonitoring = request.payload;
        chrome.storage.local.set({ isMonitoring });
        return true;
    }

    // Handle final form submission
    if (request.type === "SUBMIT_IDENTITY") {
        fetch("http://localhost:8000/api/submit", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
            body: JSON.stringify(request.payload)
        })
        .then(r => r.json())
        .then(data => {
            if (data?.riskLevel === "HIGH" || data?.status === "pending_review") {
                stats.risks += 1;
                broadcastStats();
            }
            sendResponse({ result: data });
        })
        .catch(err => sendResponse({ error: err.toString() }));
        return true;
    }

    // Handle input stream
    if (request.type === "ANALYZE_INPUT") {
        if (!isMonitoring) {
            sendResponse({ result: { status: "paused" } });
            return true;
        }

        stats.scanned += 1;
        broadcastStats();

        // Send payload to backend over REST
        fetch("http://localhost:8000/api/analyze", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-API-Key": API_KEY
            },
            body: JSON.stringify({
                ...request.payload,
                sourceUrl: sender.tab ? sender.tab.url : "unknown"
            })
        })
        .then(response => response.json())
        .then(data => {
            // Check if ML similarity flagged this as high risk
            if (data && data.riskLevel === "HIGH") {
                stats.risks += 1;
                broadcastStats();
            }
            sendResponse({ result: data });
        })
        .catch(error => {
            console.error("Backend fetch error: ", error);
            // Mock response if backend isn't ready
            sendResponse({ error: error.toString() });
        });

        // Must return true to keep the message channel open for async response Let
        return true;
    }
});
