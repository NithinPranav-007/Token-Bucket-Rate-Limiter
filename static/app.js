/**
 * Token-Bucket Rate Limiter - Real-Time Dashboard Client
 * Connects directly to FastAPI backend without static or hardcoded mock data.
 */

// Application State
let activeKey = "client-api-1";
let currentTokens = 5.0;
let burst = 5;
let rate = 2.0;
let cost = 1;
let trafficSimulationInterval = null;
let knownKeys = new Set();

// Initialize on DOM Ready
document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  fetchLimiterTelemetry();
  // Poll real-time telemetry every 800ms
  setInterval(fetchLimiterTelemetry, 800);
});

function setupEventListeners() {
  document.getElementById("input-burst").addEventListener("input", updateSliderLabels);
  document.getElementById("input-rate").addEventListener("input", updateSliderLabels);
  document.getElementById("input-cost").addEventListener("input", updateSliderLabels);

  const keyInput = document.getElementById("input-key");
  keyInput.addEventListener("change", (e) => {
    const val = e.target.value.trim();
    if (val) {
      selectKey(val);
    }
  });

  const simToggle = document.getElementById("traffic-sim-toggle");
  if (simToggle) {
    simToggle.addEventListener("change", (e) => {
      toggleTrafficSimulation(e.target.checked);
    });
  }

  updateSliderLabels();
}

// Switch between tabs
function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach((btn) => btn.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach((content) => content.classList.remove("active"));

  if (tabId === "lab") {
    document.querySelectorAll(".tab-btn")[0].classList.add("active");
    document.getElementById("tab-lab").classList.add("active");
  } else {
    document.querySelectorAll(".tab-btn")[1].classList.add("active");
    document.getElementById("tab-slides").classList.add("active");
  }
}

// Update Slider value displays
function updateSliderLabels() {
  burst = parseInt(document.getElementById("input-burst").value, 10);
  rate = parseFloat(document.getElementById("input-rate").value);
  cost = parseInt(document.getElementById("input-cost").value, 10);

  document.getElementById("val-burst").textContent = `${burst} tokens`;
  document.getElementById("val-rate").textContent = `${rate.toFixed(1)} / sec`;
  document.getElementById("val-cost").textContent = `${cost} token${cost > 1 ? "s" : ""}`;

  document.getElementById("tick-max").textContent = burst.toFixed(1);
  document.getElementById("tick-mid").textContent = (burst / 2).toFixed(1);

  // Clamp cost slider max to current burst
  const costInput = document.getElementById("input-cost");
  costInput.max = burst;
  if (parseInt(costInput.value, 10) > burst) {
    costInput.value = burst;
    cost = burst;
    document.getElementById("val-cost").textContent = `${cost} token${cost > 1 ? "s" : ""}`;
  }
}

// Dynamically select or switch client key
function selectKey(keyName) {
  activeKey = keyName;
  document.getElementById("input-key").value = keyName;
  document.getElementById("display-key").textContent = keyName;

  // Highlight chip if exists
  document.querySelectorAll(".key-chip").forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.key === keyName);
  });
}

// Fetch Real-Time Telemetry and Dynamic Buckets from Backend
async function fetchLimiterTelemetry() {
  try {
    const res = await fetch("/v1/limiter/status");
    if (!res.ok) return;

    const data = await res.json();

    // Update real server telemetry
    document.getElementById("stat-total").textContent = data.total_requests;
    document.getElementById("stat-allowed").textContent = data.total_allowed;
    document.getElementById("stat-denied").textContent = data.total_denied;
    document.getElementById("stat-keys-count").textContent = data.total_keys;

    // Update dynamic key chips from real backend buckets
    renderDynamicKeys(data.buckets);

    // Update current active key's real server-computed tokens
    const currentBucket = data.buckets.find((b) => b.key === activeKey);
    if (currentBucket) {
      updateBucketVisual(currentBucket.tokens, currentBucket.burst);
    }
  } catch (err) {
    console.debug("Telemetry fetch pending:", err);
  }
}

// Render dynamic key chips from backend buckets
function renderDynamicKeys(buckets) {
  const container = document.getElementById("key-chips-container");
  if (!container) return;

  const currentBucketKeys = new Set(buckets.map((b) => b.key));
  // If activeKey is not in known keys, add it to known
  if (activeKey) knownKeys.add(activeKey);
  buckets.forEach((b) => knownKeys.add(b.key));

  container.innerHTML = "";
  knownKeys.forEach((k) => {
    const chip = document.createElement("span");
    chip.className = `key-chip ${k === activeKey ? "active" : ""}`;
    chip.dataset.key = k;
    chip.textContent = k;
    chip.onclick = () => {
      selectKey(k);
      // If bucket has server configuration, adopt it
      const bInfo = buckets.find((b) => b.key === k);
      if (bInfo) {
        document.getElementById("input-burst").value = bInfo.burst;
        document.getElementById("input-rate").value = bInfo.rate_per_second;
        updateSliderLabels();
      }
    };
    container.appendChild(chip);
  });
}

// Send Real-Time Rate Limit Check to Backend
async function sendRateLimitCheck() {
  updateSliderLabels();
  const payload = {
    key: activeKey,
    rate_per_second: rate,
    burst: burst,
    cost: cost,
  };

  try {
    const response = await fetch("/v1/limit/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (response.ok) {
      updateBucketVisual(data.remaining_tokens, data.burst);
      updateResultBanner(data);
      recordAuditLog(data);
      fetchLimiterTelemetry();
    } else {
      showErrorBanner(data.detail || "Validation Error");
    }
  } catch (err) {
    console.error("Rate limit check failed:", err);
    showErrorBanner("Backend connection failure");
  }
}

// 5x Rapid Burst
async function triggerBurst(count) {
  for (let i = 0; i < count; i++) {
    await sendRateLimitCheck();
    await new Promise((resolve) => setTimeout(resolve, 80));
  }
}

// Toggle Live Traffic Simulator
function toggleTrafficSimulation(enable) {
  if (enable) {
    if (trafficSimulationInterval) clearInterval(trafficSimulationInterval);
    trafficSimulationInterval = setInterval(() => {
      sendRateLimitCheck();
    }, 1000);
  } else {
    if (trafficSimulationInterval) {
      clearInterval(trafficSimulationInterval);
      trafficSimulationInterval = null;
    }
  }
}

// Update Visual Cylinder
function updateBucketVisual(tokens, maxBurst) {
  currentTokens = tokens;
  burst = maxBurst;

  const fillPercent = Math.max(0, Math.min(100, (tokens / maxBurst) * 100));
  const fluidEl = document.getElementById("bucket-fluid");
  fluidEl.style.height = `${fillPercent}%`;

  document.getElementById("display-tokens").textContent = tokens.toFixed(2);
  document.getElementById("tick-max").textContent = maxBurst.toFixed(1);
  document.getElementById("tick-mid").textContent = (maxBurst / 2).toFixed(1);

  if (fillPercent < 20) {
    fluidEl.style.background = "linear-gradient(180deg, #ef4444 0%, #b91c1c 100%)";
    fluidEl.style.boxShadow = "0 0 30px rgba(239, 68, 68, 0.6)";
  } else if (fillPercent < 50) {
    fluidEl.style.background = "linear-gradient(180deg, #f59e0b 0%, #d97706 100%)";
    fluidEl.style.boxShadow = "0 0 30px rgba(245, 158, 11, 0.5)";
  } else {
    fluidEl.style.background = "linear-gradient(180deg, rgba(0, 242, 254, 0.8) 0%, rgba(79, 172, 254, 0.9) 100%)";
    fluidEl.style.boxShadow = "0 0 30px rgba(0, 242, 254, 0.5)";
  }
}

// Update Result Banner
function updateResultBanner(data) {
  const banner = document.getElementById("result-banner");
  const icon = document.getElementById("banner-icon");
  const title = document.getElementById("banner-title");
  const sub = document.getElementById("banner-sub");
  const retryContainer = document.getElementById("retry-container");
  const retryBadge = document.getElementById("banner-retry");

  if (data.allowed) {
    banner.className = "result-banner allowed";
    icon.textContent = "✅";
    title.textContent = "Request Permitted (HTTP 200)";
    sub.textContent = `Cost: ${cost} • Remaining: ${data.remaining_tokens.toFixed(2)} tokens`;
    retryContainer.style.display = "none";
  } else {
    banner.className = "result-banner denied";
    icon.textContent = "🛑";
    title.textContent = "Rate Limit Denied (HTTP 200)";
    sub.textContent = `Insufficient tokens (${data.remaining_tokens.toFixed(2)} available, ${cost} required)`;
    retryBadge.textContent = `Retry in ${data.retry_after_seconds.toFixed(2)}s`;
    retryContainer.style.display = "block";
  }
}

function showErrorBanner(msg) {
  const banner = document.getElementById("result-banner");
  banner.className = "result-banner denied";
  document.getElementById("banner-icon").textContent = "⚠️";
  document.getElementById("banner-title").textContent = "Validation Error (HTTP 422)";
  document.getElementById("banner-sub").textContent = typeof msg === "string" ? msg : JSON.stringify(msg);
  document.getElementById("retry-container").style.display = "none";
}

// Record into Live Audit Log
function recordAuditLog(data) {
  const stream = document.getElementById("audit-stream");
  const item = document.createElement("div");
  const now = new Date();
  const timeStr =
    now.toTimeString().split(" ")[0] + "." + String(now.getMilliseconds()).padStart(3, "0");

  item.className = `stream-item ${data.allowed ? "allowed" : "denied"}`;
  item.innerHTML = `
    <div class="stream-left">
      <span class="stream-key">${data.key} (cost: ${cost})</span>
      <span class="stream-time">${timeStr} • ${data.remaining_tokens.toFixed(2)} remaining</span>
    </div>
    <span class="stream-badge ${data.allowed ? "allowed" : "denied"}">
      ${data.allowed ? "ALLOWED" : `RETRY ${data.retry_after_seconds.toFixed(2)}s`}
    </span>
  `;

  stream.insertBefore(item, stream.firstChild);

  while (stream.children.length > 25) {
    stream.removeChild(stream.lastChild);
  }
}

// Reset Limiter State
async function resetLimiterState() {
  try {
    await fetch("/v1/limiter/reset", { method: "DELETE" });
    knownKeys.clear();
    document.getElementById("audit-stream").innerHTML = "";
    fetchLimiterTelemetry();
    sendRateLimitCheck();
  } catch (e) {
    console.error("Reset failed:", e);
  }
}
