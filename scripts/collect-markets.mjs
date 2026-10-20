// Standalone public-market collector generated from Ballottage 546a9b2 (Node 24). Rebuild command in README.md.
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
//#region server/polymarket.js
const PM_SLUG = "next-french-presidential-election";
const PM_LIVE_TTL_MS = 6e5;
const PM_FALLBACK_TTL_MS = 6e4;
const PM_CACHED_GRACE_MS = 36e5;
const PM_TIMEOUT_MS = 6e3;
const NAME_TO_SLUG = {
	"le pen": "lepen",
	"philippe": "philippe",
	"mélenchon": "melenchon",
	"melenchon": "melenchon",
	"attal": "attal",
	"hollande": "hollande",
	"bardella": "bardella",
	"retailleau": "retailleau",
	"lisnard": "lisnard",
	"glucksmann": "glucksmann",
	"villepin": "villepin",
	"zemmour": "zemmour",
	"tondelier": "tondelier",
	"roussel": "roussel",
	"ruffin": "ruffin",
	"knafo": "knafo",
	"lecornu": "lecornu"
};
/** Extrait les cotes (en cents, 1 décimale) d'une réponse Gamma. */
function parsePolymarketEvents(events) {
	const markets = events?.[0]?.markets || [];
	const prices = {};
	for (const market of markets) {
		const question = (market.question || market.groupItemTitle || "").toLowerCase();
		const slug = Object.entries(NAME_TO_SLUG).find(([key]) => question.includes(key))?.[1];
		if (!slug) continue;
		let price = null;
		try {
			const outcomes = typeof market.outcomePrices === "string" ? JSON.parse(market.outcomePrices) : market.outcomePrices;
			price = Array.isArray(outcomes) ? Number.parseFloat(outcomes[0]) : null;
		} catch {
			price = null;
		}
		if ((price == null || Number.isNaN(price)) && market.lastTradePrice != null) price = Number.parseFloat(market.lastTradePrice);
		if (price != null && !Number.isNaN(price)) prices[slug] = Math.round(price * 1e3) / 10;
	}
	return prices;
}
function snapshotAsOf$1(snapshot) {
	const day = typeof snapshot?.updatedAt === "string" ? snapshot.updatedAt : null;
	if (!day) return null;
	const date = /* @__PURE__ */ new Date(`${day}T00:00:00Z`);
	return Number.isNaN(date.getTime()) ? null : date.toISOString();
}
function createPolymarketClient({ snapshot, fetchImpl = fetch, now = () => /* @__PURE__ */ new Date(), liveTtlMs = PM_LIVE_TTL_MS, fallbackTtlMs = PM_FALLBACK_TTL_MS, cachedGraceMs = PM_CACHED_GRACE_MS, timeoutMs = PM_TIMEOUT_MS, slug = PM_SLUG, log = (message) => console.warn(message) } = {}) {
	let cache = {
		at: 0,
		ttl: 0,
		result: null
	};
	let lastLive = null;
	async function fetchLive(checkedAt) {
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), timeoutMs);
		try {
			const response = await fetchImpl(`https://gamma-api.polymarket.com/events?slug=${slug}`, {
				signal: controller.signal,
				headers: { "User-Agent": "second-tour/1.0" }
			});
			if (!response.ok) throw new Error(`gamma ${response.status}`);
			const prices = parsePolymarketEvents(await response.json());
			if (Object.keys(prices).length < 5) throw new Error("too few markets matched");
			return {
				prices,
				mode: "live",
				asOf: checkedAt,
				asOfPrecision: "instant",
				checkedAt
			};
		} finally {
			clearTimeout(timer);
		}
	}
	async function get() {
		const at = now().getTime();
		if (cache.result && at - cache.at < cache.ttl) return cache.result;
		const checkedAt = new Date(at).toISOString();
		try {
			const result = await fetchLive(checkedAt);
			cache = {
				at,
				ttl: liveTtlMs,
				result
			};
			lastLive = {
				at,
				result
			};
			return result;
		} catch (error) {
			log(`[polymarket] fallback: ${error.message}`);
			let fallback;
			if (lastLive && at - lastLive.at < cachedGraceMs) fallback = {
				...lastLive.result,
				mode: "cached",
				checkedAt,
				error: error.message
			};
			else fallback = {
				prices: snapshot?.markets?.polymarket || {},
				mode: "snapshot",
				asOf: snapshotAsOf$1(snapshot),
				asOfPrecision: "day",
				checkedAt,
				error: error.message
			};
			cache = {
				at,
				ttl: fallbackTtlMs,
				result: fallback
			};
			return fallback;
		}
	}
	return {
		get,
		inspectCache: () => ({ ...cache })
	};
}
//#endregion
//#region server/kalshi.js
const KX_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2";
const KX_SERIES_TICKER = "KXFRENCHPRES";
const KX_EVENT_TICKER = "KXFRENCHPRES-27";
const KX_MARKET_URL = "https://kalshi.com/markets/kxfrenchpres/french-presidential-election";
const KX_LIVE_TTL_MS = 6e5;
const KX_FALLBACK_TTL_MS = 6e4;
const KX_CACHED_GRACE_MS = 36e5;
const KX_TIMEOUT_MS = 6e3;
const SLUG_TO_TICKER = {
	lepen: "KXFRENCHPRES-27-MLEP",
	philippe: "KXFRENCHPRES-27-EPHI",
	melenchon: "KXFRENCHPRES-27-JMEL",
	hollande: "KXFRENCHPRES-27-FHOL",
	bardella: "KXFRENCHPRES-27-JBAR",
	attal: "KXFRENCHPRES-27-GATT",
	knafo: "KXFRENCHPRES-27-SKNA",
	villepin: "KXFRENCHPRES-27-DVIL",
	lisnard: "KXFRENCHPRES-27-DLIS",
	lecornu: "KXFRENCHPRES-27-SLEC",
	ruffin: "KXFRENCHPRES-27-FRUF",
	retailleau: "KXFRENCHPRES-27-BRET",
	zemmour: "KXFRENCHPRES-27-EZEM"
};
const UNLISTED_SLUGS = [
	"glucksmann",
	"tondelier",
	"roussel"
];
const TICKER_TO_SLUG = new Map(Object.entries(SLUG_TO_TICKER).map(([slug, ticker]) => [ticker, slug]));
/** Toutes les cotes à `null` : la charge utile garde ses clés même sans marché. */
function emptyQuotes() {
	const prices = {};
	for (const slug of Object.keys(SLUG_TO_TICKER)) prices[slug] = null;
	for (const slug of UNLISTED_SLUGS) prices[slug] = null;
	return prices;
}
/** Nombre de profils réellement cotés (les `null` ne comptent pas). */
function quotedCount(prices) {
	return Object.values(prices || {}).filter((value) => value != null && Number.isFinite(Number(value))).length;
}
function priceInCents(market, key) {
	const dollars = market?.[`${key}_dollars`];
	if (dollars != null) {
		const value = Number.parseFloat(dollars);
		return Number.isFinite(value) ? value * 100 : null;
	}
	const cents = market?.[key];
	if (cents == null) return null;
	const value = Number.parseFloat(cents);
	return Number.isFinite(value) ? value : null;
}
/**
* Une cote par marché, en cents (0–100, une décimale) : le milieu du carnet quand il
* existe, sinon le dernier échange. Un carnet à 0/0 n'est pas une cote à zéro, c'est
* une absence de carnet — on retombe alors sur `last_price`.
*/
function quoteFromMarket(market) {
	const bid = priceInCents(market, "yes_bid");
	const ask = priceInCents(market, "yes_ask");
	const value = bid != null && ask != null && (bid > 0 || ask > 0) ? (bid + ask) / 2 : priceInCents(market, "last_price");
	if (value == null || !Number.isFinite(value)) return null;
	return Math.min(100, Math.max(0, Math.round(value * 10) / 10));
}
/** Extrait les cotes d'une réponse `/markets` ou `/events?with_nested_markets=true`. */
function parseKalshiMarkets(payload) {
	const markets = Array.isArray(payload?.markets) ? payload.markets : Array.isArray(payload?.event?.markets) ? payload.event.markets : [];
	const prices = {};
	for (const slug of UNLISTED_SLUGS) prices[slug] = null;
	for (const market of markets) {
		const slug = TICKER_TO_SLUG.get(market?.ticker);
		if (!slug) continue;
		prices[slug] = quoteFromMarket(market);
	}
	return prices;
}
function snapshotAsOf(snapshot) {
	const day = typeof snapshot?.markets?.kalshiAsOf === "string" ? snapshot.markets.kalshiAsOf : typeof snapshot?.updatedAt === "string" ? snapshot.updatedAt : null;
	if (!day) return null;
	const date = /* @__PURE__ */ new Date(`${day}T00:00:00Z`);
	return Number.isNaN(date.getTime()) ? null : date.toISOString();
}
function createKalshiClient({ snapshot, fetchImpl = fetch, now = () => /* @__PURE__ */ new Date(), liveTtlMs = KX_LIVE_TTL_MS, fallbackTtlMs = KX_FALLBACK_TTL_MS, cachedGraceMs = KX_CACHED_GRACE_MS, timeoutMs = KX_TIMEOUT_MS, baseUrl = KX_BASE_URL, eventTicker = KX_EVENT_TICKER, minMarkets = 5, log = (message) => console.warn(message) } = {}) {
	const endpoint = `${baseUrl}/markets?event_ticker=${encodeURIComponent(eventTicker)}&limit=200`;
	let cache = {
		at: 0,
		ttl: 0,
		result: null
	};
	let lastLive = null;
	async function fetchLive(checkedAt) {
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), timeoutMs);
		try {
			const response = await fetchImpl(endpoint, {
				signal: controller.signal,
				headers: {
					"User-Agent": "second-tour/1.0",
					Accept: "application/json"
				}
			});
			if (!response.ok) throw new Error(`kalshi ${response.status}`);
			const prices = parseKalshiMarkets(await response.json());
			if (quotedCount(prices) < minMarkets) throw new Error("too few markets matched");
			return {
				prices,
				mode: "live",
				asOf: checkedAt,
				asOfPrecision: "instant",
				checkedAt,
				source: "kalshi",
				url: KX_MARKET_URL
			};
		} finally {
			clearTimeout(timer);
		}
	}
	async function get() {
		const at = now().getTime();
		if (cache.result && at - cache.at < cache.ttl) return cache.result;
		const checkedAt = new Date(at).toISOString();
		try {
			const result = await fetchLive(checkedAt);
			cache = {
				at,
				ttl: liveTtlMs,
				result
			};
			lastLive = {
				at,
				result
			};
			return result;
		} catch (error) {
			log(`[kalshi] fallback: ${error.message}`);
			let fallback;
			if (lastLive && at - lastLive.at < cachedGraceMs) fallback = {
				...lastLive.result,
				mode: "cached",
				checkedAt,
				error: error.message
			};
			else {
				const snapshotPrices = snapshot?.markets?.kalshi || {};
				fallback = quotedCount(snapshotPrices) >= 1 ? {
					prices: snapshotPrices,
					mode: "snapshot",
					asOf: snapshotAsOf(snapshot),
					asOfPrecision: "day",
					checkedAt,
					source: "kalshi",
					url: KX_MARKET_URL,
					error: error.message
				} : {
					prices: emptyQuotes(),
					mode: "unavailable",
					asOf: null,
					asOfPrecision: null,
					checkedAt,
					source: "kalshi",
					url: KX_MARKET_URL,
					error: error.message
				};
			}
			cache = {
				at,
				ttl: fallbackTtlMs,
				result: fallback
			};
			return fallback;
		}
	}
	return {
		get,
		inspectCache: () => ({ ...cache })
	};
}
//#endregion
//#region src/lib.js
const PARIS = "Europe/Paris";
({
	h1: {
		lepen: 33,
		philippe: 18,
		melenchon: 15,
		glucksmann: 8,
		hollande: 4,
		attal: 6,
		retailleau: 7,
		tondelier: 2.5,
		zemmour: 2.5,
		villepin: 2,
		roussel: 1,
		lisnard: 1
	},
	h2: {},
	h3: {}
}).h1;
Object.freeze([{
	id: "polymarket",
	label: "Polymarket",
	short: "PM"
}, {
	id: "kalshi",
	label: "Kalshi",
	short: "KA"
}]);
const partsFormatters = /* @__PURE__ */ new Map();
function partsFormatter(timeZone) {
	if (!partsFormatters.has(timeZone)) partsFormatters.set(timeZone, new Intl.DateTimeFormat("en-US", {
		timeZone,
		hourCycle: "h23",
		weekday: "short",
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit"
	}));
	return partsFormatters.get(timeZone);
}
function tzParts(date, timeZone = PARIS) {
	const parts = {};
	for (const part of partsFormatter(timeZone).formatToParts(date)) {
		if (part.type === "literal") continue;
		parts[part.type] = part.type === "weekday" ? part.value : Number(part.value);
	}
	if (parts.hour === 24) parts.hour = 0;
	return parts;
}
function civilDate(date, timeZone = PARIS) {
	const parts = tzParts(date, timeZone);
	return {
		year: parts.year,
		month: parts.month,
		day: parts.day
	};
}
Object.freeze([
	{
		id: "blue",
		value: "#2457FF",
		label: "Bleu"
	},
	{
		id: "red",
		value: "#FF2E4D",
		label: "Rouge"
	},
	{
		id: "yellow",
		value: "#FFD028",
		label: "Jaune"
	},
	{
		id: "green",
		value: "#14C47C",
		label: "Vert"
	}
]);
Object.freeze({
	franceinfo: "franceinfo",
	"Libération": "LIBÉ",
	"20 Minutes": "20 MIN.",
	BFMTV: "BFMTV",
	"Public Sénat": "PUB. SÉNAT",
	"France 24": "FRANCE 24",
	RFI: "RFI",
	"Le Monde": "LE MONDE",
	"Le Figaro": "LE FIGARO"
});
//#endregion
//#region src/series.js
/** Les 13 candidats du banc, dans l'ordre des profils suivis par l'ingestion. */
const BENCH = Object.freeze([
	"lepen",
	"philippe",
	"melenchon",
	"glucksmann",
	"hollande",
	"attal",
	"retailleau",
	"tondelier",
	"zemmour",
	"villepin",
	"roussel",
	"lisnard",
	"bardella"
]);
/**
* Le début des tendances de la Course (Paper, page 18, 12 octobre 2026 : « Depuis avril ») :
* les sondages d'une série vivante que détaille `firstRoundSeries` (un point par sondage,
* ses parts comprises) et l'historique des cotes des deux marchés (`markets.history`).
*/
const TREND_FROM = "2026-04-01";
//#endregion
//#region src/market-history.js
/**
* L'historique des cotes des deux marchés de prédiction (Polymarket, Kalshi), en ¢ de
* victoire finale (Paper, page 18, 12 octobre 2026 : « Les deux marchés depuis avril »), tel
* que /api/data le sert (`markets.history.<marché>.<slug> = [{day, cents}]`, depuis le
* 1ᵉʳ avril) et que la Course le trace : un panneau par candidat pour les six profils les
* mieux cotés aujourd'hui, Polymarket en trait plein, Kalshi en tirets. Isomorphe : le
* serveur (relevé, rattrapage, charge utile, server/market-history.js) et l'appareil (les
* panneaux) appliquent les mêmes fonctions. Aucune E/S, aucun React.
*
* Règles : deux marchés, jamais fusionnés ni moyennés ; Bardella est un profil à part,
* jamais ajouté à Le Pen ; un jour sans cote reste sans point (aucun jour inventé, aucun 0).
*/
/** Les deux marchés, chacun sa ligne. */
const HISTORY_VENUES = Object.freeze(["polymarket", "kalshi"]);
const ISO_DAY$1 = /^\d{4}-\d{2}-\d{2}$/;
const pad2 = (value) => String(value).padStart(2, "0");
/** La date ISO (AAAA-MM-JJ) d'un instant, heure de Paris ; null pour une date illisible. */
function parisDay(at) {
	const date = at instanceof Date ? at : new Date(at);
	if (!Number.isFinite(date.getTime())) return null;
	const civil = civilDate(date);
	return `${civil.year}-${pad2(civil.month)}-${pad2(civil.day)}`;
}
/** Une cote en ¢ au dixième, entre 0 et 100 ; null pour une valeur illisible ou hors bornes. */
function roundCents(value) {
	if (value === null || value === void 0 || value === "") return null;
	const number = Number(value);
	if (!Number.isFinite(number) || number < 0 || number > 100) return null;
	return Math.round(number * 10) / 10;
}
/**
* Une cote par jour (heure de Paris) depuis des relevés horodatés : la dernière de chaque
* jour, au dixième de cent ; les jours avant `from` (le 1ᵉʳ avril) écartés ; du plus ancien au
* plus récent.
* @param {Array<{ at: number|string|Date, cents: number }>} observations
* @param {{ from?: string }} [options]
* @returns {Array<{ day: string, cents: number }>}
*/
function dailyQuotes(observations, { from = TREND_FROM } = {}) {
	const byDay = /* @__PURE__ */ new Map();
	const timed = (Array.isArray(observations) ? observations : []).map((entry) => ({
		time: new Date(entry?.at).getTime(),
		cents: roundCents(entry?.cents)
	})).filter((entry) => Number.isFinite(entry.time) && entry.cents !== null).sort((a, b) => a.time - b.time);
	for (const entry of timed) {
		const day = parisDay(entry.time);
		if (day && day >= from) byDay.set(day, entry.cents);
	}
	return [...byDay].sort(([x], [y]) => x < y ? -1 : 1).map(([day, cents]) => ({
		day,
		cents
	}));
}
/**
* Les points utiles au tracé : le point intérieur d'un palier (même cote la veille et le
* lendemain) disparaît, la ligne reste la même ; le premier et le dernier restent toujours.
* @param {Array<{ day: string, cents: number }>} points du plus ancien au plus récent
*/
function thinQuotes(points) {
	const list = Array.isArray(points) ? points : [];
	return list.filter((point, index) => index === 0 || index === list.length - 1 || !(list[index - 1].cents === point.cents && list[index + 1].cents === point.cents));
}
/**
* La cote en direct sur l'historique : le jour du relevé (`asOf`, heure de Paris) prend la
* cote du moment, l'historique d'avant reste tel quel. Un relevé plus ancien que le dernier
* jour gardé ne change rien.
* @param {Array<{ day: string, cents: number }>} points
* @param {number|null} cents la cote en direct
* @param {string|null} asOf l'instant du relevé
*/
function withLiveQuote(points, cents, asOf) {
	const list = Array.isArray(points) ? points : [];
	const value = roundCents(cents);
	const day = asOf ? parisDay(asOf) : null;
	if (value === null || !day) return list;
	const last = list.at(-1);
	if (last && last.day > day) return list;
	if (last?.day === day) return [...list.slice(0, -1), {
		day,
		cents: value
	}];
	return [...list, {
		day,
		cents: value
	}];
}
const priceOf = (prices, slug) => {
	const value = prices?.[slug];
	return value === null || value === void 0 || value === "" || !Number.isFinite(Number(value)) ? null : Number(value);
};
/**
* Les profils des panneaux : ceux du banc (les douze candidats et Bardella, chacun à part)
* classés par leur cote du jour, la plus haute des deux marchés (un classement, jamais une
* cote fusionnée), six au plus ; à égalité, l'ordre des slugs. Un profil qu'aucun marché ne
* cote aujourd'hui n'a pas de panneau.
* @param {{ polymarket?: Record<string, number|null>, kalshi?: Record<string, number|null> }} prices
* @param {{ limit?: number }} [options]
* @returns {string[]}
*/
function panelSlugs(prices, { limit = 6 } = {}) {
	return BENCH.map((slug) => ({
		slug,
		top: Math.max(priceOf(prices?.polymarket, slug) ?? -1, priceOf(prices?.kalshi, slug) ?? -1)
	})).filter((entry) => entry.top >= 0).sort((a, b) => b.top - a.top || (a.slug < b.slug ? -1 : 1)).slice(0, limit).map((entry) => entry.slug);
}
/** Le relevé en direct d'un marché sert-il de cote du jour ? (en direct, ou ses dernières cotes). */
const fresh = (quote) => quote && (quote.mode === "live" || quote.mode === "cached");
/**
* `markets.history` de /api/data : pour chaque marché, les profils des panneaux (classés sur
* les cotes de la charge utile), leurs cotes de chaque jour depuis le 1ᵉʳ avril (`stored`) avec
* la cote du moment pour le jour de son relevé quand elle est en direct (le bout de la ligne est
* la cote que la table affiche), allégées des paliers. Un marché sans historique pour un profil
* ne lui donne aucune ligne.
* @param {object} input
* @param {{ polymarket?: Record<string, Array<{day: string, cents: number}>>, kalshi?: Record<string, Array<{day: string, cents: number}>> }} input.stored
* @param {{ polymarket?: { prices: object, mode: string, asOf: string|null }, kalshi?: { prices: object, mode: string, asOf: string|null } }} input.quotes
* @param {string} [input.from]
* @returns {{ polymarket: Record<string, Array<{day: string, cents: number}>>, kalshi: Record<string, Array<{day: string, cents: number}>> }}
*/
function historyPayload({ stored = {}, quotes = {}, from = TREND_FROM } = {}) {
	const slugs = panelSlugs({
		polymarket: quotes.polymarket?.prices,
		kalshi: quotes.kalshi?.prices
	});
	const out = {};
	for (const venue of HISTORY_VENUES) {
		const quote = quotes[venue];
		out[venue] = {};
		for (const slug of slugs) {
			let points = (stored?.[venue]?.[slug] ?? []).filter((point) => ISO_DAY$1.test(point?.day) && point.day >= from && roundCents(point.cents) !== null);
			if (fresh(quote)) points = withLiveQuote(points, priceOf(quote.prices, slug), quote.asOf);
			const thinned = thinQuotes(points.map((point) => ({
				day: point.day,
				cents: roundCents(point.cents)
			})));
			if (thinned.length) out[venue][slug] = thinned;
		}
	}
	return out;
}
//#endregion
//#region server/market-history.js
const GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events";
const CLOB_HISTORY_URL = "https://clob.polymarket.com/prices-history";
/** Une requête d'historique abandonnée après ce délai. */
const HISTORY_TIMEOUT_MS = 1e4;
/** Premier rattrapage après le démarrage (après la première ingestion des sondages, 30 s). */
const HISTORY_BOOT_DELAY_MS = 45e3;
/** Le service regarde l'heure toutes les 10 minutes (rattrapage du jour, relevé de 20 h). */
const HISTORY_TICK_MS = 6e5;
/** Un rattrapage manqué se retente au plus une fois par heure. */
const HISTORY_RETRY_MS = 36e5;
const BENCH_SET = new Set(BENCH);
const DAY_MS = 864e5;
/**
* Le jeton YES de chaque marché du banc dans l'événement Gamma : `{ slug: jeton }`. Le
* profil se lit dans la question comme le fait parsePolymarketEvents (server/polymarket.js) ;
* le jeton YES est celui de l'issue « Yes » (la première sinon).
* @param {object[]} events la réponse de GET /events?slug=…
* @returns {Record<string, string>}
*/
function polymarketTokens(events) {
	const tokens = {};
	for (const market of events?.[0]?.markets ?? []) {
		const question = String(market?.question || market?.groupItemTitle || "").toLowerCase();
		const slug = Object.entries(NAME_TO_SLUG).find(([key]) => question.includes(key))?.[1];
		if (!slug || !BENCH_SET.has(slug) || tokens[slug]) continue;
		let ids = market.clobTokenIds;
		let outcomes = market.outcomes;
		try {
			if (typeof ids === "string") ids = JSON.parse(ids);
			if (typeof outcomes === "string") outcomes = JSON.parse(outcomes);
		} catch {
			continue;
		}
		if (!Array.isArray(ids) || !ids.length) continue;
		const yes = Array.isArray(outcomes) ? outcomes.findIndex((outcome) => String(outcome).toLowerCase() === "yes") : -1;
		const token = String(ids[yes >= 0 ? yes : 0] ?? "");
		if (/^\d{1,100}$/.test(token)) tokens[slug] = token;
	}
	return tokens;
}
/**
* Les relevés de GET /prices-history : `[{ at, cents }]` (le prix du YES, de 0 à 1, en ¢).
* @param {{ history?: Array<{ t: number, p: number }> }} json
*/
function parsePolymarketHistory(json) {
	return (Array.isArray(json?.history) ? json.history : []).map((point) => ({
		at: Number(point?.t) * 1e3,
		cents: Number(point?.p) * 100
	})).filter((point) => Number.isFinite(point.at) && roundCents(point.cents) !== null);
}
/** Un prix Kalshi en ¢ : les dollars en chaîne (« 0.4300 ») ou les anciens cents entiers. */
function kalshiCents(block, key) {
	const dollars = block?.[`${key}_dollars`];
	if (dollars !== void 0 && dollars !== null) {
		const value = Number.parseFloat(dollars);
		return Number.isFinite(value) ? value * 100 : null;
	}
	const cents = block?.[key];
	if (cents === void 0 || cents === null) return null;
	const value = Number.parseFloat(cents);
	return Number.isFinite(value) ? value : null;
}
/**
* La cote d'une bougie Kalshi : la clôture du jour, sinon la précédente (un jour sans
* échange), sinon le milieu acheteur/vendeur à la clôture ; null sans aucun prix.
*/
function kalshiCandleCents(candle) {
	const close = kalshiCents(candle?.price, "close");
	if (close !== null) return close;
	const previous = kalshiCents(candle?.price, "previous");
	if (previous !== null) return previous;
	const bid = kalshiCents(candle?.yes_bid, "close");
	const ask = kalshiCents(candle?.yes_ask, "close");
	return bid !== null && ask !== null ? (bid + ask) / 2 : null;
}
/**
* Les relevés de GET …/candlesticks : `[{ at, cents }]`, l'instant de fin de chaque bougie.
* @param {{ candlesticks?: object[] }} json
*/
function parseKalshiCandles(json) {
	return (Array.isArray(json?.candlesticks) ? json.candlesticks : []).map((candle) => ({
		at: Number(candle?.end_period_ts) * 1e3,
		cents: kalshiCandleCents(candle)
	})).filter((point) => Number.isFinite(point.at) && roundCents(point.cents) !== null);
}
/**
* Écrit des cotes du jour : une ligne d'un jour passé n'est jamais réécrite, celle de
* `today` (ou d'après) prend la cote la plus récente.
* @param {object} db server/db.js
* @param {Array<{ venue: string, slug: string, day: string, cents: number }>} rows
* @param {{ today: string }} options
* @returns {Promise<number>} lignes écrites (insérées ou mises à jour)
*/
async function saveQuotes(db, rows, { today }) {
	const unique = /* @__PURE__ */ new Map();
	for (const row of rows) if (HISTORY_VENUES.includes(row?.venue) && BENCH_SET.has(row.slug) && /^\d{4}-\d{2}-\d{2}$/.test(row.day) && roundCents(row.cents) !== null) unique.set(`${row.venue}|${row.slug}|${row.day}`, row);
	const clean = [...unique.values()];
	if (!clean.length) return 0;
	return (await db.query(`insert into market_quotes (venue, slug, day, cents)
     select * from unnest($1::text[], $2::text[], $3::date[], $4::float8[])
     on conflict (venue, slug, day) do update set cents = excluded.cents
     where market_quotes.day >= $5::date and market_quotes.cents is distinct from excluded.cents`, [
		clean.map((row) => row.venue),
		clean.map((row) => row.slug),
		clean.map((row) => row.day),
		clean.map((row) => roundCents(row.cents)),
		today
	]))?.rowCount ?? 0;
}
/**
* Les cotes gardées depuis `from` : `{ polymarket: { slug: [{day, cents}] }, kalshi: … }`, du
* plus ancien au plus récent.
*/
async function loadQuotes(db, { from = TREND_FROM } = {}) {
	const rows = await db.many("select venue, slug, day::text as day, cents from market_quotes where day >= $1::date order by venue, slug, day", [from]);
	const out = Object.fromEntries(HISTORY_VENUES.map((venue) => [venue, {}]));
	for (const row of rows) {
		if (!out[row.venue]) continue;
		(out[row.venue][row.slug] ??= []).push({
			day: row.day,
			cents: Number(row.cents)
		});
	}
	return out;
}
/** Même règle en mémoire (sans base) : un jour passé n'est jamais réécrit. */
function saveInMemory(memory, rows, { today }) {
	let written = 0;
	for (const row of rows) {
		const cents = roundCents(row.cents);
		if (!HISTORY_VENUES.includes(row.venue) || !BENCH_SET.has(row.slug) || cents === null) continue;
		const key = `${row.venue}|${row.slug}|${row.day}`;
		if (memory.has(key) && (row.day < today || memory.get(key) === cents)) continue;
		memory.set(key, cents);
		written += 1;
	}
	return written;
}
function loadFromMemory(memory, { from = TREND_FROM } = {}) {
	const out = Object.fromEntries(HISTORY_VENUES.map((venue) => [venue, {}]));
	for (const [key, cents] of [...memory].sort(([x], [y]) => x < y ? -1 : 1)) {
		const [venue, slug, day] = key.split("|");
		if (day < from) continue;
		(out[venue][slug] ??= []).push({
			day,
			cents
		});
	}
	return out;
}
async function fetchJson(fetchImpl, url, timeoutMs) {
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), timeoutMs);
	try {
		const response = await fetchImpl(url, {
			signal: controller.signal,
			headers: {
				"User-Agent": "second-tour/1.0",
				Accept: "application/json"
			}
		});
		if (!response.ok) throw new Error(`HTTP ${response.status}`);
		return await response.json();
	} catch (error) {
		throw new Error(error?.name === "AbortError" ? "délai dépassé" : error?.message || String(error));
	} finally {
		clearTimeout(timer);
	}
}
/**
* Le service de l'historique des cotes.
* @param {object} options
* @param {object|null} [options.db] server/db.js ; null : en mémoire
* @param {{ polymarket?: () => Promise<object>, kalshi?: () => Promise<object> }} [options.live]
*   les cotes en direct des deux clients (`get()`), pour le relevé de 20 h
* @param {typeof fetch} [options.fetchImpl]
* @param {() => Date} [options.clock]
* @param {Console} [options.log]
*/
function createMarketHistory({ db = null, live = {}, fetchImpl = globalThis.fetch, clock = () => /* @__PURE__ */ new Date(), log = console, timeoutMs = HISTORY_TIMEOUT_MS, bootDelayMs = HISTORY_BOOT_DELAY_MS, tickMs = HISTORY_TICK_MS, retryMs = HISTORY_RETRY_MS, recordHour = 20, from = TREND_FROM } = {}) {
	const memory = /* @__PURE__ */ new Map();
	let stored = Object.fromEntries(HISTORY_VENUES.map((venue) => [venue, {}]));
	let version = 0;
	let memo = null;
	const done = {
		backfill: {},
		record: {}
	};
	const attempts = {};
	const reported = /* @__PURE__ */ new Set();
	let running = null;
	let timers = [];
	let stopped = true;
	const warnOnce = (key, message) => {
		if (reported.has(key)) return;
		reported.add(key);
		log.warn?.(message);
	};
	async function reload() {
		stored = db ? await loadQuotes(db, { from }) : loadFromMemory(memory, { from });
		version += 1;
	}
	async function save(rows, today) {
		if (!rows.length) return 0;
		const written = db ? await saveQuotes(db, rows, { today }) : saveInMemory(memory, rows, { today });
		if (written) await reload();
		return written;
	}
	/** Polymarket : l'événement Gamma, puis l'historique de chaque marché du banc. */
	async function fetchPolymarket() {
		const tokens = polymarketTokens(await fetchJson(fetchImpl, `${GAMMA_EVENTS_URL}?slug=${encodeURIComponent(PM_SLUG)}`, timeoutMs));
		if (!Object.keys(tokens).length) throw new Error("aucun marché du banc dans l'événement");
		const rows = [];
		for (const [slug, token] of Object.entries(tokens)) try {
			const json = await fetchJson(fetchImpl, `${CLOB_HISTORY_URL}?market=${encodeURIComponent(token)}&interval=max&fidelity=1440`, timeoutMs);
			for (const quote of dailyQuotes(parsePolymarketHistory(json), { from })) rows.push({
				venue: "polymarket",
				slug,
				...quote
			});
		} catch (error) {
			warnOnce(`polymarket:${slug}:${error.message}`, `[markets-history] polymarket ${slug} : ${error.message}`);
		}
		return rows;
	}
	/** Kalshi : les bougies quotidiennes de chaque ticker du banc depuis le 1ᵉʳ avril. */
	async function fetchKalshi(now) {
		const start = Math.floor((Date.parse(`${from}T00:00:00Z`) - DAY_MS) / 1e3);
		const end = Math.floor(now.getTime() / 1e3);
		const rows = [];
		for (const [slug, ticker] of Object.entries(SLUG_TO_TICKER)) {
			if (!BENCH_SET.has(slug)) continue;
			try {
				const json = await fetchJson(fetchImpl, `${KX_BASE_URL}/series/${encodeURIComponent(KX_SERIES_TICKER)}/markets/${encodeURIComponent(ticker)}/candlesticks?start_ts=${start}&end_ts=${end}&period_interval=1440`, timeoutMs);
				for (const quote of dailyQuotes(parseKalshiCandles(json), { from })) rows.push({
					venue: "kalshi",
					slug,
					...quote
				});
			} catch (error) {
				warnOnce(`kalshi:${slug}:${error.message}`, `[markets-history] kalshi ${slug} : ${error.message}`);
			}
		}
		return rows;
	}
	/** Le rattrapage d'un marché : son historique depuis le 1ᵉʳ avril ; isolé de l'autre. */
	async function backfillVenue(venue, now) {
		const today = parisDay(now);
		attempts[venue] = now.getTime();
		try {
			const rows = venue === "polymarket" ? await fetchPolymarket() : await fetchKalshi(now);
			if (!rows.length) throw new Error("aucun historique lisible");
			const written = await save(rows, today);
			done.backfill[venue] = today;
			log.info?.(`[markets-history] ${venue} : ${rows.length} cotes relues, ${written} écrites`);
			return {
				venue,
				ok: true,
				rows: rows.length,
				written
			};
		} catch (error) {
			warnOnce(`${venue}:backfill:${error.message}`, `[markets-history] rattrapage ${venue} en échec : ${error.message}`);
			return {
				venue,
				ok: false,
				error: error.message
			};
		}
	}
	/** Le relevé du jour depuis les cotes en direct d'un marché (seulement en direct). */
	async function recordVenue(venue, now) {
		const today = parisDay(now);
		try {
			const quote = await live[venue]?.();
			if (!quote || quote.mode !== "live" || parisDay(quote.asOf) !== today) return {
				venue,
				ok: false,
				error: `cotes ${quote?.mode ?? "absentes"}`
			};
			const rows = Object.entries(quote.prices ?? {}).filter(([slug, cents]) => BENCH_SET.has(slug) && roundCents(cents) !== null).map(([slug, cents]) => ({
				venue,
				slug,
				day: today,
				cents
			}));
			if (!rows.length) return {
				venue,
				ok: false,
				error: "aucune cote"
			};
			const written = await save(rows, today);
			done.record[venue] = today;
			return {
				venue,
				ok: true,
				rows: rows.length,
				written
			};
		} catch (error) {
			warnOnce(`${venue}:record:${error.message}`, `[markets-history] relevé ${venue} en échec : ${error.message}`);
			return {
				venue,
				ok: false,
				error: error.message
			};
		}
	}
	/**
	* Un passage : le rattrapage de chaque marché pas encore rattrapé aujourd'hui (au plus une
	* tentative par heure), puis, à partir de 20 h, le relevé du jour de chaque marché.
	*/
	async function tick(now = clock()) {
		if (running) return running;
		running = (async () => {
			const today = parisDay(now);
			const results = [];
			await Promise.all(HISTORY_VENUES.map(async (venue) => {
				if (done.backfill[venue] !== today && (attempts[venue] === void 0 || now.getTime() - attempts[venue] >= retryMs)) results.push(await backfillVenue(venue, now));
				if (tzParts(now).hour >= recordHour && done.record[venue] !== today) results.push(await recordVenue(venue, now));
			}));
			return results;
		})();
		try {
			return await running;
		} finally {
			running = null;
		}
	}
	return {
		tick,
		backfill: (now = clock()) => Promise.all(HISTORY_VENUES.map((venue) => backfillVenue(venue, now))),
		record: (now = clock()) => Promise.all(HISTORY_VENUES.map((venue) => recordVenue(venue, now))),
		reload,
		/** Les cotes gardées, par marché et par profil (tests). */
		stored: () => stored,
		/**
		* `markets.history` de /api/data : les profils des panneaux, leurs cotes depuis le
		* 1ᵉʳ avril et, au bout, la cote en direct du jour (src/market-history.js).
		* @param {{ polymarket?: object, kalshi?: object }} quotes les réponses des deux clients
		*/
		payload(quotes = {}) {
			if (memo && memo.version === version && memo.polymarket === quotes.polymarket && memo.kalshi === quotes.kalshi) return memo.value;
			const value = historyPayload({
				stored,
				quotes,
				from
			});
			memo = {
				version,
				polymarket: quotes.polymarket,
				kalshi: quotes.kalshi,
				value
			};
			return value;
		},
		/** Relit la base dès qu'elle est migrée, rattrape après 45 s, puis regarde l'heure toutes les 10 min. */
		start() {
			if (!stopped) return;
			stopped = false;
			const begin = async () => {
				try {
					await db?.whenReady?.();
					if (db) await reload();
				} catch (error) {
					log.warn?.(`[markets-history] lecture initiale impossible : ${error.message}`);
				}
				if (stopped) return;
				const first = setTimeout(() => tick().catch(() => {}), bootDelayMs);
				first.unref?.();
				const every = setInterval(() => tick().catch(() => {}), tickMs);
				every.unref?.();
				timers = [first, every];
			};
			begin();
		},
		stop() {
			stopped = true;
			for (const timer of timers) {
				clearTimeout(timer);
				clearInterval(timer);
			}
			timers = [];
		}
	};
}
//#endregion
//#region server/market-archive.js
const DAY = 864e5;
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
function buildMarketArchive({ quotes, history, previous = null, now = /* @__PURE__ */ new Date() }) {
	const today = parisDay(now);
	if (!today) throw new Error("Invalid collection date");
	if (previous && previous.schemaVersion !== 1) throw new Error("Unsupported previous market archive");
	const markets = {
		status: {},
		history: {}
	};
	for (const venue of HISTORY_VENUES) {
		const quote = quotes?.[venue];
		const at = Date.parse(quote?.asOf);
		if (quote?.mode !== "live" || !Number.isFinite(at) || now.getTime() - at > DAY || at > now.getTime() + 3e5) throw new Error(`${venue}: no fresh live quotes; the previous archive is kept`);
		const prices = Object.fromEntries(Object.entries(quote.prices ?? {}).filter(([slug, value]) => /^[a-z][a-z0-9_-]{0,63}$/.test(slug) && (value === null || roundCents(value) !== null)));
		if (Object.values(prices).filter((value) => value !== null).length < 5) throw new Error(`${venue}: too few quotes`);
		markets[venue] = prices;
		markets.status[venue] = {
			mode: "live",
			asOf: quote.asOf,
			checkedAt: quote.checkedAt ?? quote.asOf
		};
		markets.history[venue] = {};
		for (const slug of BENCH) {
			const byDay = /* @__PURE__ */ new Map();
			for (const [rows, replace] of [[previous?.markets?.history?.[venue]?.[slug], false], [history?.[venue]?.[slug], true]]) for (const point of Array.isArray(rows) ? rows : []) {
				if (!ISO_DAY.test(point?.day) || point.day < "2026-04-01" || point.day > today || roundCents(point.cents) === null) continue;
				if (!byDay.has(point.day) || replace && point.day === today) byDay.set(point.day, {
					day: point.day,
					cents: roundCents(point.cents)
				});
			}
			const points = withLiveQuote([...byDay.values()].sort((a, b) => a.day.localeCompare(b.day)), prices[slug], quote.asOf);
			if (points.length) markets.history[venue][slug] = points;
		}
	}
	return {
		schemaVersion: 1,
		collectedAt: now.toISOString(),
		sources: {
			polymarket: "https://polymarket.com/event/next-french-presidential-election",
			kalshi: "https://kalshi.com/markets/kxfrenchpres/french-presidential-election"
		},
		markets
	};
}
//#endregion
//#region scripts/collect-markets.mjs
const output = resolve(process.argv[2] ?? "data/markets.json");
let previous = null;
try {
	previous = JSON.parse(await readFile(output, "utf8"));
} catch (error) {
	if (error.code !== "ENOENT") throw error;
}
const history = createMarketHistory();
const [polymarket, kalshi, backfill] = await Promise.all([
	createPolymarketClient().get(),
	createKalshiClient().get(),
	history.backfill()
]);
for (const result of backfill) if (!result.ok && !Object.keys(previous?.markets?.history?.[result.venue] ?? {}).length) throw new Error(`${result.venue}: initial history unavailable (${result.error})`);
const archive = buildMarketArchive({
	quotes: {
		polymarket,
		kalshi
	},
	history: history.stored(),
	previous
});
await mkdir(dirname(output), { recursive: true });
await writeFile(`${output}.tmp`, `${JSON.stringify(archive, null, 2)}\n`);
await rename(`${output}.tmp`, output);
console.log(JSON.stringify({
	output,
	collectedAt: archive.collectedAt,
	asOf: Object.fromEntries(Object.entries(archive.markets.status).map(([venue, status]) => [venue, status.asOf]))
}));
//#endregion
export {};
