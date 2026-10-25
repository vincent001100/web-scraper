// Solvix Scraper: everything that moves on the page.
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const sites = Object.fromEntries(window.SITES.map((s) => [s.key, s]));
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

const state = { site: null, pages: 3, all: false, job: null, rows: [], fields: [], ext: "xlsx" };
const FORMAT_NAMES = { xlsx: "Excel", csv: "CSV", pdf: "PDF", json: "JSON", txt: "Text" };

// ---------- the 1-2-3 steps at the top ----------
function setStep(n) {
  $$(".step").forEach((el) => {
    const s = Number(el.dataset.step);
    el.classList.toggle("is-active", s === n);
    el.classList.toggle("is-done", s < n);
    el.querySelector(".step-dot").textContent = s < n ? "✓" : s;
  });
  $$(".step-line").forEach((el, i) => el.classList.toggle("is-done", i + 2 <= n));
}

// ---------- numbers that count up smoothly ----------
function countTo(el, target, { duration = 900, suffix = "" } = {}) {
  const from = Number(el.dataset.value || 0);
  el.dataset.value = target;
  if (reduceMotion || from === target) { el.textContent = target.toLocaleString() + suffix; return; }
  const start = performance.now();
  const tick = (now) => {
    const t = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = Math.round(from + (target - from) * eased).toLocaleString() + suffix;
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// ---------- step 1: choose a site ----------
$$(".site").forEach((card) => card.addEventListener("click", () => selectSite(card.dataset.key)));

function selectSite(key) {
  state.site = sites[key];
  $$(".site").forEach((c) => c.classList.toggle("is-selected", c.dataset.key === key));

  const chips = $("#field-chips");
  chips.innerHTML = "";
  state.site.fields.forEach((f, i) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.style.animationDelay = `${i * 60}ms`;
    chip.textContent = f.replace(/_/g, " ");
    chips.append(chip);
  });

  const paged = state.site.paged;
  $("#single-page-note").hidden = paged;
  $(".toggle").hidden = !paged;
  $("#stepper").hidden = !paged;
  const options = $("#options");
  const firstTime = options.hidden;
  options.hidden = false;
  if (firstTime) options.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderPages() {
  $("#pages").textContent = state.pages;
  $("#stepper").classList.toggle("is-off", state.all);
  $$("#stepper button").forEach((b) => {
    const d = Number(b.dataset.delta);
    b.disabled = state.all || (d < 0 && state.pages <= 1) || (d > 0 && state.pages >= 50);
  });
}
$$("#stepper button").forEach((b) => b.addEventListener("click", () => {
  state.pages = Math.min(50, Math.max(1, state.pages + Number(b.dataset.delta)));
  renderPages();
}));
$("#all-pages").addEventListener("change", (e) => { state.all = e.target.checked; renderPages(); });
renderPages();

$("#site-filter").addEventListener("input", (e) => {
  const q = e.target.value.trim().toLowerCase();
  let shown = 0;
  $$(".site").forEach((c) => {
    const match = !q || c.dataset.search.includes(q);
    c.hidden = !match;
    shown += match;
  });
  $("#no-sites").hidden = shown > 0;
});

// ---------- step 2: collect, with live updates from the server ----------
$("#start").addEventListener("click", startRun);

function startRun() {
  if (!state.site) return;
  const pages = !state.site.paged ? 1 : state.all ? 0 : state.pages;
  setStep(2);
  $("#start").classList.add("is-busy");
  $("#results").hidden = true;
  $("#error").hidden = true;
  $("#log").innerHTML = "";
  $("#run-title").textContent = `Collecting from ${state.site.name}…`;
  $("#collect-note").textContent = "Waiting…";
  const counter = $("#counter");
  counter.dataset.value = 0;
  counter.textContent = "0";
  const bar = $(".bar");
  bar.classList.toggle("is-unknown", pages === 0);
  bar.classList.remove("is-complete");
  $("#bar-fill").style.width = "0%";
  $$("#timeline li").forEach((li) => li.className = "");

  const run = $("#run");
  run.hidden = false;
  run.style.animation = "none"; run.offsetHeight; run.style.animation = "";  // replay the entrance
  run.scrollIntoView({ behavior: "smooth", block: "start" });

  const mark = (name, cls) => { $(`#timeline [data-t="${name}"]`).className = cls; };
  const source = new EventSource(`/api/scrape?site=${state.site.key}&pages=${pages}`);
  let pagesDone = 0;

  source.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "check") mark("check", "is-active");
    if (msg.type === "allowed") { mark("check", "is-done"); mark("collect", "is-active"); }
    if (msg.type === "page") {
      pagesDone = msg.page;
      countTo(counter, msg.total, { duration: 600 });
      $("#collect-note").textContent = `Page ${msg.page}${pages ? ` of up to ${pages}` : ""} · ${msg.total.toLocaleString()} records so far`;
      if (pages) $("#bar-fill").style.width = `${Math.min(msg.page / pages, 1) * 100}%`;
      const li = document.createElement("li");
      li.innerHTML = `<span>Page ${msg.page}</span><b>+${msg.found} records</b>`;
      $("#log").prepend(li);
      while ($("#log").children.length > 5) $("#log").lastChild.remove();
    }
    if (msg.type === "done") {
      source.close();
      mark("collect", "is-done");
      mark("ready", "is-done");
      bar.classList.remove("is-unknown");
      bar.classList.add("is-complete");
      $("#bar-fill").style.width = "100%";
      countTo(counter, msg.rows.length, { duration: 400 });
      $("#run-title").textContent = "Done";
      Object.assign(state, { job: msg.job, rows: msg.rows, fields: msg.fields });
      setTimeout(() => showResults(pagesDone, msg.seconds), reduceMotion ? 0 : 650);
    }
    if (msg.type === "error") {
      source.close();
      const active = $("#timeline li.is-active");
      if (active) active.className = "is-failed";
      $("#run-title").textContent = "We had to stop";
      $("#error").textContent = msg.message;
      $("#error").hidden = false;
      $("#start").classList.remove("is-busy");
      setStep(1);
    }
  };
  source.onerror = () => {
    source.close();
    $("#error").textContent = "Lost connection to the app. Is it still running in the Terminal?";
    $("#error").hidden = false;
    $("#start").classList.remove("is-busy");
  };
}

// ---------- step 3: results ----------
function showResults(pages, seconds) {
  setStep(3);
  $("#start").classList.remove("is-busy");
  const results = $("#results");
  results.hidden = false;
  results.style.animation = "none"; results.offsetHeight; results.style.animation = "";
  $("#results-title").textContent = `${state.site.name}: your data is ready`;
  $("#results-sub").textContent = `Collected just now from ${new URL(state.site.url).hostname}`;
  $$("[data-count]").forEach((el) => { el.dataset.value = 0; el.textContent = "0"; });
  countTo($("#s-rows"), state.rows.length);
  countTo($("#s-pages"), pages);
  countTo($("#s-fields"), state.fields.length);
  $("#s-time").textContent = `${seconds}s`;
  $("#row-filter").value = "";
  renderTable("");
  setFormat(state.ext);
  setTimeout(() => results.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
}

const MAX_SHOWN = 300; // keep the page fast; the download always has everything

function renderTable(query) {
  const q = query.trim().toLowerCase();
  const thead = $("#table thead");
  const tbody = $("#table tbody");
  thead.innerHTML = "";
  const head = document.createElement("tr");
  state.fields.forEach((f) => {
    const th = document.createElement("th");
    th.textContent = f.replace(/_/g, " ");
    head.append(th);
  });
  thead.append(head);

  const matching = q ? state.rows.filter((r) => state.fields.some((f) => String(r[f]).toLowerCase().includes(q))) : state.rows;
  tbody.innerHTML = "";
  matching.slice(0, MAX_SHOWN).forEach((row, i) => {
    const tr = document.createElement("tr");
    if (!q && i < 25) { tr.className = "fade"; tr.style.animationDelay = `${i * 28}ms`; }
    state.fields.forEach((f) => {
      const td = document.createElement("td");
      highlight(td, String(row[f] ?? ""), q);
      tr.append(td);
    });
    tbody.append(tr);
  });
  const shown = Math.min(matching.length, MAX_SHOWN);
  $("#showing").textContent = matching.length === state.rows.length
    ? `Showing ${shown.toLocaleString()} of ${state.rows.length.toLocaleString()} records`
    : `${matching.length.toLocaleString()} matching records`;
}

// Wrap the searched-for text in <mark> without ever inserting raw HTML
function highlight(td, text, q) {
  const at = q ? text.toLowerCase().indexOf(q) : -1;
  if (at < 0) { td.textContent = text; return; }
  const mark = document.createElement("mark");
  mark.textContent = text.slice(at, at + q.length);
  td.append(text.slice(0, at), mark, text.slice(at + q.length));
}

let filterTimer;
$("#row-filter").addEventListener("input", (e) => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => renderTable(e.target.value), 120);
});

function setFormat(ext) {
  state.ext = ext;
  $$("#formats button").forEach((b) => b.setAttribute("aria-checked", b.dataset.ext === ext));
  const link = $("#download");
  link.classList.remove("is-done");
  link.href = `/api/download/${state.job}/${ext}`;
  link.querySelector("span").textContent = `Download ${FORMAT_NAMES[ext]}`;
}
$$("#formats button").forEach((b) => b.addEventListener("click", () => setFormat(b.dataset.ext)));

$("#download").addEventListener("click", () => {
  const link = $("#download");
  link.classList.add("is-done");
  link.querySelector("span").textContent = `Downloaded ${FORMAT_NAMES[state.ext]} ✓`;
  setTimeout(() => setFormat(state.ext), 2200);
});

$("#again").addEventListener("click", () => {
  setStep(1);
  $("#run").hidden = true;
  $("#results").hidden = true;
  $("#choose").scrollIntoView({ behavior: "smooth", block: "start" });
});
