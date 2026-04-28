// Defense-in-depth: only activate on whitelisted government domains
const ALLOWED_DOMAIN_PATTERNS = [/\.gov\.in$/, /\.nic\.in$/, /^localhost$/, /^127\.0\.0\.1$/];
if (!ALLOWED_DOMAIN_PATTERNS.some(p => p.test(window.location.hostname))) {
    throw new Error("FraudGuard: non-government domain — monitoring disabled.");
}

const injectStyles = () => {
    const style = document.createElement("style");
    style.innerHTML = `
        .fg-tooltip {
            position: fixed;
            background-color: #ef4444;
            color: white;
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-family: system-ui, -apple-system, sans-serif;
            font-weight: 600;
            z-index: 2147483647;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            pointer-events: none;
            transition: opacity 0.3s ease;
            margin-top: 4px;
        }
        .fg-tooltip-medium { background-color: #f97316 !important; }
        .fg-input-high {
            border: 2px solid #ef4444 !important;
            box-shadow: 0 0 8px rgba(239,68,68,0.4) !important;
            outline: none !important;
        }
        .fg-input-medium {
            border: 2px solid #f97316 !important;
            box-shadow: 0 0 8px rgba(249,115,22,0.4) !important;
            outline: none !important;
        }
        #fg-submit-banner {
            position: fixed;
            top: 0; left: 0; right: 0;
            z-index: 2147483647;
            padding: 14px 24px;
            font-family: system-ui, -apple-system, sans-serif;
            font-size: 14px;
            font-weight: 600;
            text-align: center;
            display: none;
            box-shadow: 0 4px 20px rgba(0,0,0,0.25);
            transition: all 0.3s ease;
        }
        #fg-submit-banner.fg-checking  { background:#1e40af; color:#fff; display:block; }
        #fg-submit-banner.fg-success   { background:#166534; color:#fff; display:block; }
        #fg-submit-banner.fg-warning   { background:#92400e; color:#fff; display:block; }
        #fg-submit-banner.fg-blocked   { background:#991b1b; color:#fff; display:block; }
    `;
    document.head.appendChild(style);
};

injectStyles();

// ── Layer 1: Device fingerprint ───────────────────────────────────────────────
// Collects stable, privacy-safe browser signals. No PII. Consistent per device.

function collectDeviceFingerprint() {
    try {
        const signals = [
            navigator.userAgent        || "",
            navigator.language         || "",
            String(screen.width)       + "x" + String(screen.height),
            String(screen.colorDepth),
            Intl.DateTimeFormat().resolvedOptions().timeZone || "",
            String(navigator.hardwareConcurrency || 0),
            String(navigator.maxTouchPoints      || 0),
        ];

        // Canvas fingerprint (pixel rendering differences per GPU/driver)
        try {
            const canvas = document.createElement("canvas");
            const ctx    = canvas.getContext("2d");
            ctx.textBaseline = "top";
            ctx.font         = "14px 'Arial'";
            ctx.fillText("FraudGuard🛡", 2, 2);
            signals.push(canvas.toDataURL().slice(-32)); // last 32 chars of data URI
        } catch (_) { /* canvas blocked */ }

        const raw  = signals.join("|");
        // Simple DJB2 hash — good enough for a device fingerprint ID
        let hash   = 5381;
        for (let i = 0; i < raw.length; i++) {
            hash = ((hash << 5) + hash) ^ raw.charCodeAt(i);
        }
        return (hash >>> 0).toString(16).padStart(8, "0");
    } catch (_) {
        return "unknown";
    }
}

// Compute once per page load, cache it
const DEVICE_ID = collectDeviceFingerprint();

// ── Banner for submit results ─────────────────────────────────────────────────

function createBanner() {
    const el = document.createElement("div");
    el.id = "fg-submit-banner";
    document.body.prepend(el);
    return el;
}

function showSubmitBanner(message, type) {
    let banner = document.getElementById("fg-submit-banner") || createBanner();
    banner.className = `fg-${type}`;
    banner.textContent = `🛡 FraudGuard: ${message}`;
    if (type === "success") {
        setTimeout(() => { banner.style.display = "none"; }, 4000);
    }
}

// ── Field category inference ──────────────────────────────────────────────────

function inferFieldCategory(element) {
    const hints = [
        element.id || "",
        element.name || "",
        element.placeholder || "",
        element.getAttribute("aria-label") || "",
        element.getAttribute("data-field") || "",
    ];

    if (element.id) {
        const label = document.querySelector(`label[for="${element.id}"]`);
        if (label) hints.push(label.innerText || label.textContent || "");
    }
    const parentLabel = element.closest("label");
    if (parentLabel) hints.push(parentLabel.innerText || parentLabel.textContent || "");

    const combined = hints.join(" ").toLowerCase();

    if (/aadhaar|aadhar|adhar|\bpan\b|pan_no|pan_num|voter[\s_-]?id|passport|uid\b|gov[\s_-]?id|national[\s_-]?id|id[\s_-]?number|identity[\s_-]?no|ssn|social[\s_-]?sec/.test(combined)) {
        return "GovID";
    }
    if (/e[\s_-]?mail/.test(combined)) {
        return "EmailAddress";
    }
    if (/\bname\b|naam|applicant|full[\s_-]?name|first[\s_-]?name|last[\s_-]?name|surname|farmer[\s_-]?name/.test(combined)) {
        return "FullName";
    }
    if (/phone|mobile|contact|tel/.test(combined)) {
        return "PhoneNumber";
    }

    return null;
}

// ── State ─────────────────────────────────────────────────────────────────────

let inputState        = {};
let isMonitoring      = true;
let interceptedForms  = new WeakSet();

chrome.storage.onChanged.addListener((changes) => {
    if (changes.isMonitoring) {
        isMonitoring = changes.isMonitoring.newValue;
        if (!isMonitoring) clearAllWarnings();
    }
});

function getFormContext(element) {
    const form = element.closest ? element.closest('form') : element;
    if (!form) return "headless-input";
    return form.id || form.name || form.action || "generic-form";
}

// ── Real-time field monitoring ────────────────────────────────────────────────

document.addEventListener("keyup", (event) => {
    if (!isMonitoring) return;
    const target = event.target;
    if (!["INPUT", "TEXTAREA"].includes(target.tagName) || target.type === "password") return;

    const category = inferFieldCategory(target);
    if (!category) return;

    const rawId = target.name || target.id || target.placeholder || "unknown";
    if (!inputState[rawId]) inputState[rawId] = { keystrokes: [], deletions: 0, pastes: 0 };

    if (event.key === "Backspace" || event.key === "Delete") {
        inputState[rawId].deletions += 1;
    } else {
        inputState[rawId].keystrokes.push(Date.now());
    }

    clearTimeout(inputState[rawId].timer);
    inputState[rawId].timer = setTimeout(() => {
        const ks              = inputState[rawId].keystrokes;
        const timeToCompleteMs = ks.length > 1 ? ks[ks.length - 1] - ks[0] : 0;
        const cps             = timeToCompleteMs > 0 ? (ks.length / (timeToCompleteMs / 1000)).toFixed(2) : 0;

        const payload = {
            formContext: getFormContext(target),
            fieldName:  category,
            value:      target.value,
            behavior: {
                keystrokesCount:  ks.length,
                deletionsCount:   inputState[rawId].deletions,
                pastesCount:      inputState[rawId].pastes,
                timeToCompleteMs,
                cps:              parseFloat(cps),
            },
            // device_id is not sent on real-time analyze calls (only on submit)
        };

        chrome.runtime.sendMessage({ type: "ANALYZE_INPUT", payload }, (response) => {
            const result = response?.result;
            if (result && (result.riskLevel === "HIGH" || result.riskLevel === "MEDIUM")) {
                showWarning(target, result.message, result.riskLevel);
            } else {
                clearWarning(target);
            }
        });
    }, 1200);
});

document.addEventListener("paste", (event) => {
    if (!isMonitoring) return;
    const target = event.target;
    if (!["INPUT", "TEXTAREA"].includes(target.tagName)) return;
    const rawId = target.name || target.id || "unknown";
    if (!inputState[rawId]) inputState[rawId] = { keystrokes: [], deletions: 0, pastes: 0 };
    inputState[rawId].pastes += 1;
});

// ── Form submit interception ──────────────────────────────────────────────────

function attachSubmitInterceptor(form) {
    if (interceptedForms.has(form)) return;
    interceptedForms.add(form);
    form.addEventListener("submit", handleFormSubmit, true);
}

function handleFormSubmit(event) {
    if (!isMonitoring) return;
    const form = event.currentTarget;

    const identityDetails = {};
    form.querySelectorAll("input, textarea, select").forEach(input => {
        if (input.type === "password" || !input.value || input.value.trim().length < 3) return;
        const category = inferFieldCategory(input);
        if (category) identityDetails[category] = input.value.trim();
    });

    if (Object.keys(identityDetails).length === 0) return;

    event.preventDefault();
    event.stopImmediatePropagation();

    showSubmitBanner("Verifying identity with fraud registry…", "checking");

    // Layer 1: attach device fingerprint to every submit payload
    identityDetails["device_id"] = DEVICE_ID;

    const payload = {
        formContext:     getFormContext(form),
        fieldName:       "FinalSubmit",
        value:           identityDetails.FullName || Object.values(identityDetails).find(v => v !== DEVICE_ID) || "",
        identityDetails,
        deviceId:        DEVICE_ID,
        behavior: {
            keystrokesCount: 0,
            deletionsCount:  0,
            pastesCount:     0,
            timeToCompleteMs: 0,
            cps:             0,
        },
    };

    chrome.runtime.sendMessage({ type: "SUBMIT_IDENTITY", payload }, (response) => {
        const result = response?.result;
        if (!result) {
            showSubmitBanner("Backend unreachable — submission allowed to proceed.", "warning");
            setTimeout(() => {
                form.removeEventListener("submit", handleFormSubmit, true);
                form.requestSubmit();
            }, 2000);
            return;
        }

        if (result.status === "pending_review") {
            showSubmitBanner("Submission flagged for officer review. You will be contacted shortly.", "warning");
        } else if (result.status === "success") {
            showSubmitBanner("Identity verified. Registration successful.", "success");
        } else if (result.riskLevel === "HIGH" || result.detail) {
            showSubmitBanner(result.message || result.detail || "Submission blocked — duplicate identity detected.", "blocked");
        } else {
            form.removeEventListener("submit", handleFormSubmit, true);
            form.requestSubmit();
        }
    });
}

document.querySelectorAll("form").forEach(attachSubmitInterceptor);

new MutationObserver((mutations) => {
    mutations.forEach(m => m.addedNodes.forEach(node => {
        if (node.nodeType !== 1) return;
        if (node.tagName === "FORM") attachSubmitInterceptor(node);
        node.querySelectorAll?.("form").forEach(attachSubmitInterceptor);
    }));
}).observe(document.body, { childList: true, subtree: true });

// ── Warning UI ────────────────────────────────────────────────────────────────

function showWarning(element, message, riskLevel) {
    element.classList.remove("fg-input-high", "fg-input-medium");
    element.classList.add(riskLevel === "HIGH" ? "fg-input-high" : "fg-input-medium");

    let tooltip = element._fgTooltip;
    if (!tooltip || !document.body.contains(tooltip)) {
        tooltip = document.createElement("div");
        tooltip.className = "fg-tooltip";
        document.body.appendChild(tooltip);
        element._fgTooltip = tooltip;
    }

    const rect = element.getBoundingClientRect();
    tooltip.style.left = `${rect.left}px`;
    tooltip.style.top  = `${rect.bottom + 4}px`;
    tooltip.className  = `fg-tooltip${riskLevel === "MEDIUM" ? " fg-tooltip-medium" : ""}`;
    tooltip.textContent = message;
    tooltip.style.opacity = "1";
}

function clearWarning(element) {
    element.classList.remove("fg-input-high", "fg-input-medium");
    if (element._fgTooltip) {
        element._fgTooltip.style.opacity = "0";
        setTimeout(() => { element._fgTooltip?.remove(); element._fgTooltip = null; }, 300);
    }
}

function clearAllWarnings() {
    document.querySelectorAll(".fg-input-high, .fg-input-medium").forEach(clearWarning);
}
