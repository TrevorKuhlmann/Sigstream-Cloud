// /static/js/paddle.js

// --- Configuration (same as before, single price for all buttons) ---
const CONFIG = {
    clientToken: "live_90f4589da3d6d2b6424a7e744af",
    prices: {
        starter: {
            month: "pri_01jw10e9kwzxgs6a7s9xqej03s",
            year: "pri_01jw10e9kwzxgs6a7s9xqej03s"
        },
        pro: {
            month: "pri_01jw10e9kwzxgs6a7s9xqej03s",
            year: "pri_01jw10e9kwzxgs6a7s9xqej03s"
        }
    }
};

// --- State mirrors the inline script you had ---
let currentBillingCycle = "month";
let currentCountry = "US";
let paddleInitialized = false;

// Expose the small surface you already use in landing.html
window.updateBillingCycle = function (cycle) {
    currentBillingCycle = cycle;
    const monthlyBtn = document.getElementById("monthlyBtn");
    const yearlyBtn = document.getElementById("yearlyBtn");
    if (monthlyBtn && yearlyBtn) {
        monthlyBtn.classList.toggle("bg-white", cycle === "month");
        yearlyBtn.classList.toggle("bg-white", cycle === "year");
    }
    updatePrices();
};

window.openCheckout = function (plan) {
    if (!paddleInitialized) return;
    // Jinja injects this onto the page; read it safely
    const emailMeta = document.querySelector('meta[name="sigstream-user-email"]');
    const email = emailMeta ? emailMeta.content : "";

    Paddle.Checkout.open({
        items: [{ priceId: CONFIG.prices[plan][currentBillingCycle], quantity: 1 }],
        settings: {
            theme: "light",
            displayMode: "overlay",
            variant: "one-page",
            successUrl: "https://sigstreamcloud.com/post-purchase"
        },
        customer: email ? { email } : undefined,
        passthrough: email ? JSON.stringify({ email }) : undefined
    });
};

// Keep identical behavior for pricing preview
async function updatePrices() {
    if (!paddleInitialized) return;

    try {
        const request = {
            items: [
                { quantity: 1, priceId: CONFIG.prices.starter[currentBillingCycle] },
                { quantity: 1, priceId: CONFIG.prices.pro[currentBillingCycle] }
            ],
            address: { countryCode: currentCountry }
        };
        const result = await Paddle.PricePreview(request);
        result.data.details.lineItems.forEach((item) => {
            const price = item.formattedTotals.subtotal;
            if (item.price.id === CONFIG.prices.starter[currentBillingCycle]) {
                const el = document.getElementById("starter-price");
                if (el) el.textContent = price;
            }
            if (item.price.id === CONFIG.prices.pro[currentBillingCycle]) {
                const el = document.getElementById("pro-price");
                if (el) el.textContent = price;
            }
        });
    } catch (e) {
        console.warn("PricePreview failed (non-fatal):", e);
    }
}

// Paddle boot
function initializePaddle() {
    Paddle.Environment.set("sandbox"); // unchanged
    Paddle.Initialize({
        token: CONFIG.clientToken,
        eventCallback: function (event) {
            console.log("Paddle event:", event);
        }
    });
    paddleInitialized = true;
    updatePrices();
}

// Wire up after DOM ready
document.addEventListener("DOMContentLoaded", () => {
    initializePaddle();
    const sel = document.getElementById("countrySelect");
    if (sel) {
        sel.addEventListener("change", (e) => {
            currentCountry = e.target.value;
            updatePrices();
        });
    }
});
