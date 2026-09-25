/**
 * Sevastopol AI — приём заявок с формы suggest.html (Cloudflare Worker).
 *
 * Секреты и настройки задаются в Dashboard → Settings → Variables and Secrets
 * или командой wrangler secret put — в коде и в git их нет:
 *   BOT_TOKEN — токен основного бота от @BotFather
 *   ADMIN_ID  — Telegram ID владельца, куда приходят заявки
 */

const LIMITS = {
  name: 120,
  category: 60,
  address: 160,
  prices: 120,
  phone: 40,
  links: 600,
  description: 900,
  contact: 80,
};

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};

const RATE_LIMIT = 5;
const RATE_WINDOW_MS = 60 * 60 * 1000;
const hits = new Map();

function rateOk(ip) {
  const now = Date.now();
  const list = (hits.get(ip) || []).filter((t) => now - t < RATE_WINDOW_MS);
  if (list.length >= RATE_LIMIT) {
    hits.set(ip, list);
    return false;
  }
  list.push(now);
  hits.set(ip, list);
  return true;
}

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Убираем управляющие символы и обрезаем длину
function clean(v, max) {
  return String(v == null ? "" : v)
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, " ")
    .trim()
    .slice(0, max);
}

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: { "Content-Type": "application/json; charset=utf-8", ...CORS_HEADERS },
  });
}

const STATUS_HTML = `<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sevastopol AI — приём заявок</title></head>
<body style="font-family:system-ui,sans-serif;background:#F1E9D8;color:#18140F;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0">
<div style="text-align:center;padding:24px">
<div style="font-size:44px">✓</div>
<h1 style="font-size:22px">Сервис заявок Sevastopol AI работает</h1>
<p style="color:rgba(24,20,15,.55)">Это технический адрес. Форма предложений — в боте: t.me/SevastopolAiBot</p>
</div></body></html>`;

function buildMessage(f) {
  const lines = [
    "📝 <b>Новое предложение места</b>",
    "",
    "🏷 Название: <b>" + esc(f.name) + "</b>",
    "📂 Категория: " + esc(f.category || "—"),
    "📍 Адрес/район: " + esc(f.address),
  ];
  if (f.prices) lines.push("💰 Цены: " + esc(f.prices));
  if (f.phone) lines.push("📞 Телефон: " + esc(f.phone));
  if (f.links) lines.push("🔗 Ссылки: " + esc(f.links.split(/\s*\n\s*/).filter(Boolean).join(" · ")));
  if (f.description) lines.push("ℹ️ Описание: " + esc(f.description));
  if (f.contact) lines.push("👤 Контакт: " + esc(f.contact));
  return lines.join("\n");
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    if (request.method === "GET") {
      return new Response(STATUS_HTML, {
        headers: { "Content-Type": "text/html; charset=utf-8", ...CORS_HEADERS },
      });
    }

    if (request.method !== "POST") {
      return json({ ok: false, error: "method_not_allowed" }, 405);
    }

    const adminId = String(env.ADMIN_ID || "").trim();
    if (!env.BOT_TOKEN || !adminId) {
      return json({ ok: false, error: "server_not_configured" }, 500);
    }

    const ip =
      request.headers.get("cf-connecting-ip") ||
      request.headers.get("x-forwarded-for") ||
      "unknown";
    if (!rateOk(ip)) {
      return json({ ok: false, error: "too_many_requests" }, 429);
    }

    let data;
    try {
      data = await request.json();
    } catch (e) {
      return json({ ok: false, error: "bad_json" }, 400);
    }
    if (typeof data !== "object" || data === null) {
      return json({ ok: false, error: "bad_json" }, 400);
    }

    const f = {
      name: clean(data.name, LIMITS.name),
      category: clean(data.category, LIMITS.category),
      address: clean(data.address, LIMITS.address),
      prices: clean(data.prices, LIMITS.prices),
      phone: clean(data.phone, LIMITS.phone),
      links: clean(data.links, LIMITS.links),
      description: clean(data.description, LIMITS.description),
      contact: clean(data.contact, LIMITS.contact),
    };

    if (!f.name || !f.address) {
      return json({ ok: false, error: "name_and_address_required" }, 400);
    }

    const resp = await fetch(
      "https://api.telegram.org/bot" + env.BOT_TOKEN + "/sendMessage",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: adminId,
          text: buildMessage(f),
          parse_mode: "HTML",
          disable_web_page_preview: true,
        }),
      }
    );

    const tg = await resp.json().catch(() => ({ ok: false }));
    if (!resp.ok || !tg.ok) {
      console.log("Telegram error:", JSON.stringify(tg));
      return json({ ok: false, error: "telegram_error" }, 502);
    }

    return json({ ok: true });
  },
};
