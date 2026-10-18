// Restaurant Finder page: calls /meta and /recommend on the same server.
// Dataset and model text is always inserted with textContent, never as HTML (UI-30, UI-31).
"use strict";

const MAX_CUISINES = 10; // same limits as Preferences, so the API never rejects what the form allows
const REQUEST_TIMEOUT_MS = 60000; // past the API's worst case (LLM timeout plus retries) (UI-05)
const BUDGET_NAMES = { "": "Any budget", low: "Low", medium: "Medium", high: "High" };

const $ = (id) => document.getElementById(id);
const state = { meta: null, cuisines: [], cuisineIndex: new Map(), searching: false, intro: null };

// --- small DOM helpers ----------------------------------------------------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) if (child != null) node.append(child);
  return node;
}

function icon(name, cls = "ico") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

const results = () => $("results");
function showResults(...nodes) {
  results().replaceChildren(...nodes.filter(Boolean));
}

// --- formatting -------------------------------------------------------------

const formatRupees = (n) => `₹${Number(n).toLocaleString("en-IN")}`;
const describeRelaxation = (change) =>
  change.replace("min_rating relaxed", "minimum rating lowered").replace("budget relaxed", "budget widened");
const monogram = (name) => (name.match(/[\p{L}\p{N}]/u) || ["?"])[0].toUpperCase();

function budgetBands(t) {
  return { low: `up to ₹${t.low_max}`, medium: `₹${t.low_max + 1}–${t.medium_max}`, high: `over ₹${t.medium_max}` };
}

// --- API ------------------------------------------------------------------

class ApiError extends Error {}

async function callApi(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let resp;
  try {
    resp = await fetch(path, { ...options, signal: controller.signal });
  } catch (err) {
    if (err.name === "AbortError") throw new ApiError("The server took too long to answer. Try again in a moment.");
    throw new ApiError("Can't reach the recommendation server. Check that it is running, then try again.");
  } finally {
    clearTimeout(timer);
  }
  if (resp.status === 422) {
    const body = await resp.json().catch(() => ({}));
    const msgs = (body.detail || []).map((e) => e.msg).filter(Boolean);
    throw new ApiError(`The server rejected the search: ${msgs.join("; ") || "invalid input"}.`);
  }
  if (resp.status === 429) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(body.detail || "Too many searches. Try again in a minute.");
  }
  if (!resp.ok) throw new ApiError(`The server had a problem (HTTP ${resp.status}). Try again.`);
  return resp.json();
}

// --- form -------------------------------------------------------------------

function fillForm(meta) {
  const cities = new Set(meta.cities);
  const location = $("location");
  location.replaceChildren(
    ...meta.cities.map((c) => el("option", { value: c, text: `${c} (all areas)` })),
    ...meta.localities.map((l) => el("option", { value: l, text: l })),
  );
  const bands = budgetBands(meta.budget_thresholds);
  document.querySelectorAll("[data-band]").forEach((node) => { node.textContent = bands[node.dataset.band]; });
  $("cuisine-list").replaceChildren(...meta.cuisines.map((c) => el("option", { value: c })));
  state.cuisineIndex = new Map(meta.cuisines.map((c) => [c.toLowerCase(), c]));
  $("brand-sub").textContent = `Zomato restaurants in ${[...cities].join(", ")}, ranked and explained by AI`;
}

function renderCuisineChips() {
  $("cuisine-chips").replaceChildren(...state.cuisines.map((c) => {
    const remove = el("button", { type: "button", "aria-label": `Remove ${c}` }, icon("x", "ico-sm"));
    remove.addEventListener("click", () => {
      state.cuisines = state.cuisines.filter((x) => x !== c);
      renderCuisineChips();
      $("cuisine-input").focus();
    });
    return el("span", { class: "chip" }, el("span", { text: c }), remove);
  }));
  const full = state.cuisines.length >= MAX_CUISINES;
  const input = $("cuisine-input");
  input.disabled = full;
  input.placeholder = full ? "Maximum of 10 reached" : state.cuisines.length ? "Add another" : "Any cuisine";
  $("cuisine-count").textContent = state.cuisines.length ? `${state.cuisines.length}/${MAX_CUISINES}` : `max ${MAX_CUISINES}`;
}

function addCuisine(raw) {
  const match = state.cuisineIndex.get(raw.trim().toLowerCase());
  if (!match) return false;
  if (!state.cuisines.includes(match) && state.cuisines.length < MAX_CUISINES) state.cuisines.push(match);
  $("cuisine-input").value = "";
  renderCuisineChips();
  return true;
}

function updateRating() {
  const slider = $("min-rating");
  const value = Number(slider.value);
  slider.style.setProperty("--fill", `${(value / 5) * 100}%`);
  const badge = $("rating-badge");
  if (value === 0) badge.replaceChildren("Any");
  else badge.replaceChildren(icon("star", "ico-sm"), `${value.toFixed(1)}+`);
}

function updateExtrasCount() {
  $("extras-count").textContent = `${$("extras").value.length}/300`;
}

function readPrefs() {
  return {
    location: $("location").value,
    budget: document.querySelector("input[name=budget]:checked").value || null,
    cuisine: [...state.cuisines],
    min_rating: Number($("min-rating").value),
    extras: $("extras").value,
  };
}

function setSearching(on) {
  state.searching = on;
  const button = $("submit");
  button.disabled = on;
  button.replaceChildren(
    on ? el("span", { class: "spinner", "aria-hidden": "true" }) : icon("search"),
    el("span", { id: "submit-label", text: on ? "Finding restaurants…" : "Find restaurants" }),
  );
  results().setAttribute("aria-busy", String(on));
}

// --- result views -------------------------------------------------------------

function banner(kind, iconName, text, action) {
  return el("div", { class: `banner ${kind}`, role: kind === "error" ? "alert" : "status" },
    icon(iconName), el("div", { class: "banner-body", text }), action);
}

function loadingView() {
  const skeletonCard = () => el("div", { class: "card skeleton", "aria-hidden": "true" },
    el("div", { class: "card-top" },
      el("div", { class: "monogram sk" }),
      el("div", { class: "card-main" },
        el("div", { class: "sk", style: "height:20px;width:55%" }),
        el("div", { class: "sk", style: "height:14px;width:35%" }))),
    el("div", { class: "sk", style: "height:44px;width:100%" }));
  return [
    el("div", { class: "loading-note" }, el("span", { class: "spinner", "aria-hidden": "true" }),
      el("span", { text: "Finding restaurants… the AI is ranking the best matches." })),
    skeletonCard(), skeletonCard(), skeletonCard(),
  ];
}

function errorView(message, retry) {
  const button = el("button", { type: "button", class: "btn-ghost" }, icon("retry", "ico-sm"), "Retry");
  button.addEventListener("click", retry);
  return banner("error", "error", message, button);
}

function emptyView(message) {
  return el("div", { class: "panel empty" },
    el("div", { class: "empty-icon" }, icon("plate")),
    el("h2", { class: "empty-title", text: message || "No restaurants match these preferences." }),
    el("p", { class: "empty-text",
      text: "Try a wider budget, a lower minimum rating, fewer cuisines, or the whole city." }));
}

function card(rec, fallback) {
  const rating = rec.rating == null
    ? el("span", { class: "rating none", text: "Not rated" })
    : el("span", { class: "rating", "aria-label": `Rated ${rec.rating.toFixed(1)} out of 5` },
        icon("star", "ico-sm"), rec.rating.toFixed(1), el("span", { class: "rating-of", text: "/ 5" }));
  const cost = rec.estimated_cost == null
    ? el("span", { class: "cost", text: "Cost for two not available" })
    : el("span", { class: "cost" }, el("strong", { text: formatRupees(rec.estimated_cost) }), " for two");

  const standard = rec.explanation_source === "template";
  const why = standard
    ? el("div", { class: "why standard" },
        el("span", { class: "why-label", text: fallback ? "Standard description" : "Standard description (no AI explanation)" }),
        el("p", { text: rec.explanation }))
    : el("div", { class: "why" }, icon("sparkle"), el("p", { text: rec.explanation }));

  return el("li", { class: "card" },
    el("div", { class: "card-top" },
      el("span", { class: "rank", "aria-hidden": "true", text: String(rec.rank) }),
      el("div", { class: "monogram", "aria-hidden": "true" }, monogram(rec.name),
        el("span", { class: "monogram-rank", text: String(rec.rank) })),
      el("div", { class: "card-main" },
        el("h3", { class: "card-name" }, el("span", { class: "sr-only", text: `${rec.rank}. ` }), rec.name),
        rec.locality ? el("span", { class: "card-place" }, icon("pin", "ico-sm"), rec.locality) : null,
        el("div", { class: "tags" }, ...rec.cuisine.map((c) => el("span", { class: "tag", text: c })))),
      el("div", { class: "card-stats" }, rating, cost)),
    why);
}

function resultsView(data) {
  const nodes = [];
  if (data.relaxed_constraints.length) {
    const changes = data.relaxed_constraints.map(describeRelaxation).join("; ");
    nodes.push(banner("warning", "warning", `Nothing matched exactly, so the search was loosened: ${changes}.`));
  }
  if (!data.recommendations.length) {
    nodes.push(emptyView(data.message));
    return nodes;
  }
  if (data.message) nodes.push(el("p", { class: "note" }, icon("info", "ico-sm"), data.message));
  if (data.llm_fallback) {
    nodes.push(banner("info", "info",
      "AI ranking is unavailable right now, so these are sorted by rating and reviews, with standard descriptions."));
  }
  if (data.summary) {
    nodes.push(el("div", { class: `panel summary${data.llm_fallback ? " plain" : ""}` },
      el("span", { class: "summary-label" }, icon(data.llm_fallback ? "info" : "sparkle", "ico-sm"),
        data.llm_fallback ? "Summary" : "AI summary"),
      el("p", { class: "summary-text", text: data.summary })));
  }
  nodes.push(el("ol", { class: "cards", "aria-label": "Recommended restaurants" },
    ...data.recommendations.map((rec) => card(rec, data.llm_fallback))));
  return nodes;
}

// Small screens: after results, a one-line summary of the search replaces the form.
function collapseForm(prefs) {
  const chip = (iconName, text) => el("span", { class: "summary-chip" }, icon(iconName, "ico-sm"), el("span", { text }));
  const cities = new Set(state.meta.cities);
  const chips = [
    chip("pin", cities.has(prefs.location) ? `${prefs.location} (all)` : prefs.location),
    chip("tune", prefs.budget ? `${BUDGET_NAMES[prefs.budget]} · ${budgetBands(state.meta.budget_thresholds)[prefs.budget]}` : "Any budget"),
  ];
  if (prefs.cuisine.length) {
    chips.push(chip("plate", prefs.cuisine.length > 1 ? `${prefs.cuisine[0]} +${prefs.cuisine.length - 1}` : prefs.cuisine[0]));
  }
  if (prefs.min_rating > 0) chips.push(chip("star", `Min ${prefs.min_rating.toFixed(1)}`));
  if (prefs.extras.trim()) {
    const extras = prefs.extras.trim();
    chips.push(chip("sparkle", extras.length > 28 ? `${extras.slice(0, 27)}…` : extras));
  }
  $("summary-chips").replaceChildren(...chips);
  $("filters").classList.add("collapsed");
}

// --- flows ----------------------------------------------------------------------

async function search() {
  if (state.searching) return; // one request at a time (UI-03)
  const prefs = readPrefs();
  setSearching(true);
  showResults(...loadingView()); // old results are cleared, never shown under new inputs (UI-32)
  try {
    const data = await callApi("/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(prefs),
    });
    showResults(...resultsView(data));
    if (data.recommendations.length) collapseForm(prefs);
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    showResults(errorView(err.message, search));
  } finally {
    setSearching(false);
  }
  if (window.matchMedia("(max-width: 1023px)").matches) results().scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadMeta() {
  $("search-fields").disabled = true; // no empty dropdowns while /meta is missing (UI-02)
  try {
    state.meta = await callApi("/meta");
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    showResults(errorView(err.message, loadMeta));
    return;
  }
  fillForm(state.meta);
  $("search-fields").disabled = false;
  if (results().querySelector(".banner.error")) showResults(state.intro); // a retry worked
}

function init() {
  state.intro = $("intro");
  $("search").addEventListener("submit", (event) => { event.preventDefault(); search(); });
  $("min-rating").addEventListener("input", updateRating);
  $("extras").addEventListener("input", updateExtrasCount);
  const cuisineInput = $("cuisine-input");
  cuisineInput.addEventListener("input", () => addCuisine(cuisineInput.value)); // picked from the list
  cuisineInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault(); // Enter adds a cuisine; it doesn't submit the form
      addCuisine(cuisineInput.value);
    } else if (event.key === "Backspace" && !cuisineInput.value && state.cuisines.length) {
      state.cuisines.pop();
      renderCuisineChips();
    }
  });
  $("edit-search").addEventListener("click", () => {
    $("filters").classList.remove("collapsed");
    $("location").focus();
  });
  updateRating();
  updateExtrasCount();
  renderCuisineChips();
  loadMeta();
}

document.addEventListener("DOMContentLoaded", init);
