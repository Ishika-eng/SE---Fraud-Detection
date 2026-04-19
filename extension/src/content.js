// Defense-in-depth: only activate on whitelisted government domains
const ALLOWED_DOMAIN_PATTERNS = [/\.gov\.in$/, /\.nic\.in$/, /^localhost$/, /^127\.0\.0\.1$/];
if (!ALLOWED_DOMAIN_PATTERNS.some(p => p.test(window.location.hostname))) {
    throw new Error("FraudGuard: non-government domain — monitoring disabled.");
}

// Inject simple visual styles for warnings
const injectStyles = () => {
    const style = document.createElement("style");
    style.innerHTML = `
        .fraud-alert-tooltip {
            position: absolute;
            background-color: #ef4444; /* High: Red */
            color: white;
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-family: system-ui, -apple-system, sans-serif;
            font-weight: 600;
            z-index: 10000;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            pointer-events: none;
            transition: opacity 0.3s ease, transform 0.3s ease;
            margin-top: 4px;
        }
        .fraud-tooltip-medium {
            background-color: #f97316 !important; /* Medium: Orange */
        }
        .fraud-input-warning {
            border: 2px solid #ef4444 !important;
            box-shadow: 0 0 8px rgba(239, 68, 68, 0.3) !important;
            outline: none !important;
        }
        .fraud-input-medium {
            border: 2px solid #f97316 !important;
            box-shadow: 0 0 8px rgba(249, 115, 22, 0.3) !important;
            outline: none !important;
        }
    `;
    document.head.appendChild(style);
};

injectStyles();

// State tracking
let inputState = {};
let isMonitoring = true;

// Listen for storage changes if user disables extension
chrome.storage.onChanged.addListener((changes) => {
    if (changes.isMonitoring) {
        isMonitoring = changes.isMonitoring.newValue;
        if (!isMonitoring) clearAllWarnings();
    }
});

function getFormContext(element) {
    const form = element.closest('form');
    if (!form) return "headless-input";
    // Extract form identity (id, name, or action)
    return form.id || form.name || form.action || "generic-form";
}

document.addEventListener("keyup", (event) => {
    if (!isMonitoring) return;
    
    const target = event.target;
    if (["INPUT", "TEXTAREA"].includes(target.tagName) && target.type !== "password") {
        
        const fieldName = target.name || target.id || target.placeholder || "unknown";
        const value = target.value;
        const timestamp = Date.now();

        // Initialize state for field
        if (!inputState[fieldName]) {
            inputState[fieldName] = { keystrokes: [], deletions: 0, pastes: 0 };
        }

        // Track deletions
        if (event.key === "Backspace" || event.key === "Delete") {
            inputState[fieldName].deletions += 1;
        } else {
            inputState[fieldName].keystrokes.push(timestamp);
        }

        // Debounce sending to background worker
        clearTimeout(inputState[fieldName].timer);
        inputState[fieldName].timer = setTimeout(() => {
            const timeToCompleteMs = inputState[fieldName].keystrokes.length > 1 ? 
                (inputState[fieldName].keystrokes[inputState[fieldName].keystrokes.length - 1] - inputState[fieldName].keystrokes[0]) : 0;
            
            // Calculate typing speed (chars per second)
            const cps = timeToCompleteMs > 0 ? (inputState[fieldName].keystrokes.length / (timeToCompleteMs / 1000)).toFixed(2) : 0;

            const payload = {
                formContext: getFormContext(target),
                fieldName,
                value,
                behavior: {
                    keystrokesCount: inputState[fieldName].keystrokes.length,
                    deletionsCount: inputState[fieldName].deletions,
                    pastesCount: inputState[fieldName].pastes,
                    timeToCompleteMs,
                    cps: parseFloat(cps)
                }
            };

            // Fire to background script
            chrome.runtime.sendMessage({ type: "ANALYZE_INPUT", payload }, (response) => {
                const result = response?.result;
                if (result && (result.riskLevel === "HIGH" || result.riskLevel === "MEDIUM")) {
                    showWarning(target, result.message, result.riskLevel);
                } else {
                    clearWarning(target);
                }
            });
        }, 1200); // 1.2s typing debounce
    }
});

// Track mass pasting (a huge fraud indicator)
document.addEventListener("paste", (event) => {
    if (!isMonitoring) return;
    const target = event.target;
    if (["INPUT", "TEXTAREA"].includes(target.tagName)) {
        const fieldName = target.name || target.id || "unknown";
        if (!inputState[fieldName]) inputState[fieldName] = { keystrokes: [], deletions: 0, pastes: 0 };
        inputState[fieldName].pastes += 1;
    }
});

function showWarning(element, message, riskLevel) {
    // Reset classes
    element.classList.remove("fraud-input-warning", "fraud-input-medium");
    
    // Apply correct class
    if (riskLevel === "HIGH") {
        element.classList.add("fraud-input-warning");
    } else {
        element.classList.add("fraud-input-medium");
    }
    
    let tooltip = element._fraudTooltip;
    if (!tooltip || !document.body.contains(tooltip)) {
        tooltip = document.createElement("div");
        tooltip.className = "fraud-alert-tooltip";
        
        // Position it right below the input
        const rect = element.getBoundingClientRect();
        tooltip.style.left = `${rect.left + window.scrollX}px`;
        tooltip.style.top = `${rect.bottom + window.scrollY}px`;
        
        document.body.appendChild(tooltip); 
        element._fraudTooltip = tooltip;
    }
    
    tooltip.innerText = message;
    tooltip.style.opacity = "1";

    // Toggle color class for tooltip
    if (riskLevel === "MEDIUM") {
        tooltip.classList.add("fraud-tooltip-medium");
    } else {
        tooltip.classList.remove("fraud-tooltip-medium");
    }
}

function clearWarning(element) {
    element.classList.remove("fraud-input-warning", "fraud-input-medium");
    if (element._fraudTooltip) {
        element._fraudTooltip.style.opacity = "0";
        setTimeout(() => {
            if (element._fraudTooltip) {
                element._fraudTooltip.remove();
                element._fraudTooltip = null;
            }
        }, 300);
    }
}

function clearAllWarnings() {
    document.querySelectorAll('.fraud-input-warning').forEach(clearWarning);
}
