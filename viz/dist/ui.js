// The work panel (left): grepper, results, executed SQL, inspector, lens switcher,
// audit tables, theme toggle; plus the key, tooltip and status over the field.
// Every piece of data is inserted as text (textContent / text nodes). innerHTML is
// never used.
function byId(id, ctor) {
    const el = document.getElementById(id);
    if (!(el instanceof ctor))
        throw new Error(`#${id} missing or not a ${ctor.name}`);
    return el;
}
/** Create an element with optional class and text. */
function h(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls)
        el.className = cls;
    if (text !== undefined)
        el.textContent = text;
    return el;
}
const SVG_NS = "http://www.w3.org/2000/svg";
/** A small inline-SVG swatch whose colours are CSS variables (so it follows the theme). */
function swatch(kind, color, opacity = 1) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("width", kind === "line" ? "18" : "14");
    svg.setAttribute("height", "14");
    svg.setAttribute("aria-hidden", "true");
    svg.classList.add("swatch");
    const circle = (r) => {
        const c = document.createElementNS(SVG_NS, "circle");
        c.setAttribute("cx", "7");
        c.setAttribute("cy", "7");
        c.setAttribute("r", String(r));
        return c;
    };
    if (kind === "line") {
        const l = document.createElementNS(SVG_NS, "line");
        l.setAttribute("x1", "1");
        l.setAttribute("y1", "7");
        l.setAttribute("x2", "17");
        l.setAttribute("y2", "7");
        l.style.stroke = color;
        l.style.strokeOpacity = String(opacity);
        l.style.strokeWidth = "1.5";
        svg.append(l);
    }
    else if (kind === "dot") {
        const c = circle(4);
        c.style.fill = color;
        c.style.fillOpacity = String(opacity);
        svg.append(c);
    }
    else if (kind === "hollow") {
        const c = circle(3.6);
        c.style.fill = "none";
        c.style.stroke = color;
        c.style.strokeWidth = "1.25";
        svg.append(c);
    }
    else if (kind === "ring") {
        const dot = circle(3);
        dot.style.fill = "var(--ramp-mid)";
        const ring = circle(5.8);
        ring.style.fill = "none";
        ring.style.stroke = color;
        ring.style.strokeWidth = "1.5";
        svg.append(dot, ring);
    }
    else {
        const dot = circle(3);
        dot.style.fill = color;
        const ring = circle(6);
        ring.style.fill = "none";
        ring.style.stroke = color;
        ring.style.strokeWidth = "1.6";
        svg.append(dot, ring);
    }
    return svg;
}
export function renderParts(parts) {
    const frag = document.createDocumentFragment();
    for (const p of parts) {
        if (p.m) {
            const m = document.createElement("mark");
            m.textContent = p.t;
            frag.append(m);
        }
        else {
            frag.append(document.createTextNode(p.t));
        }
    }
    return frag;
}
/** Only http(s) links become anchors; anything else is shown as text. */
function safeHref(url) {
    try {
        const u = new URL(url);
        return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
    }
    catch {
        return null;
    }
}
const fmt = new Intl.NumberFormat("en");
export class Ui {
    source = byId("source", HTMLElement);
    q = byId("q", HTMLInputElement);
    mode = byId("mode", HTMLSelectElement);
    scope = byId("scope", HTMLSelectElement);
    form = byId("search-form", HTMLFormElement);
    searchStatus = byId("search-status", HTMLElement);
    results = byId("results", HTMLOListElement);
    sql = byId("sql", HTMLDetailsElement);
    sqlText = byId("sql-text", HTMLElement);
    inspector = byId("inspector", HTMLElement);
    audit = byId("audit", HTMLDetailsElement);
    auditBody = byId("audit-body", HTMLElement);
    key = byId("key", HTMLElement);
    tooltip = byId("tooltip", HTMLElement);
    fieldStatus = byId("field-status", HTMLElement);
    themeButton = byId("theme-toggle", HTMLButtonElement);
    panelToggle = byId("panel-toggle", HTMLButtonElement);
    panelBody = byId("panel-body", HTMLElement);
    semantic = byId("semantic", HTMLInputElement);
    offline = false;
    hits = [];
    constructor(cb) {
        const fire = () => cb.onSearch(this.q.value, this.mode.value, this.scope.value);
        this.form.addEventListener("submit", (e) => {
            e.preventDefault();
            fire();
        });
        this.q.addEventListener("input", fire);
        this.mode.addEventListener("change", fire);
        this.scope.addEventListener("change", fire);
        this.results.addEventListener("click", (e) => {
            const btn = e.target?.closest("button[data-hit]");
            if (!(btn instanceof HTMLButtonElement))
                return;
            const hit = this.hits[Number(btn.dataset.hit)];
            if (hit)
                cb.onPickHit(hit);
        });
        const onIdClick = (e) => {
            const btn = e.target?.closest("button[data-id]");
            if (btn instanceof HTMLButtonElement && btn.dataset.id)
                cb.onSelectId(btn.dataset.id);
        };
        this.inspector.addEventListener("click", onIdClick);
        this.auditBody.addEventListener("click", onIdClick);
        for (const radio of document.querySelectorAll('input[name="lens"]')) {
            radio.addEventListener("change", () => {
                if (radio.checked)
                    cb.onLens(radio.value === "coverage" ? "coverage" : "structure");
            });
        }
        this.semantic.addEventListener("change", () => cb.onSemantic(this.semantic.checked));
        byId("fit", HTMLButtonElement).addEventListener("click", () => cb.onFit());
        this.themeButton.addEventListener("click", () => cb.onTheme());
        this.audit.addEventListener("toggle", () => {
            if (this.audit.open)
                cb.onAuditOpen();
        });
        this.panelToggle.addEventListener("click", () => this.setPanelOpen(this.panelBody.hidden !== false));
        // Narrow screens stack the panel above the field: start with its lower part folded so
        // the field is in view; the search stays open. Wide screens always show everything.
        const narrow = window.matchMedia("(max-width: 760px)");
        this.setPanelOpen(!narrow.matches);
        narrow.addEventListener("change", () => this.setPanelOpen(!narrow.matches));
    }
    setPanelOpen(open) {
        this.panelBody.hidden = !open;
        this.panelToggle.setAttribute("aria-expanded", String(open));
        this.panelToggle.textContent = open ? "Hide panel" : "Show panel";
    }
    // ------------------------------------------------------------ status
    setSource(text, detail = "") {
        this.source.textContent = text;
        this.source.title = detail;
    }
    setThemeLabel(current) {
        this.themeButton.textContent = current === "dark" ? "Light theme" : "Dark theme";
        this.themeButton.setAttribute("aria-label", `Switch to the ${current === "dark" ? "light" : "dark"} theme`);
    }
    setFieldStatus(text) {
        this.fieldStatus.hidden = text === null;
        this.fieldStatus.textContent = text ?? "";
    }
    /** Offline: the grepper falls back to label search and says so. */
    setOffline(offline) {
        this.offline = offline;
        this.mode.disabled = offline;
        this.scope.disabled = offline;
        this.q.placeholder = offline ? "Search labels (offline)" : "Grep the catalogue";
        if (offline)
            this.setSearchStatus("offline: label search only (API not reachable)", "offline");
        else
            this.setSearchStatus("", null);
    }
    setSearchStatus(text, tone) {
        this.searchStatus.textContent = text;
        this.searchStatus.dataset.tone = tone ?? "";
    }
    focusSearch() {
        this.q.focus();
        this.q.select();
    }
    clearSearchBox() {
        this.q.value = "";
    }
    // ------------------------------------------------------------ results
    showSearching(q) {
        this.setSearchStatus(`Searching for “${q}”…`, null);
    }
    clearResults() {
        this.hits = [];
        this.results.replaceChildren();
        this.sql.hidden = true;
        this.sqlText.textContent = "";
        this.setOffline(this.offline);
    }
    showSearchError(message, resp) {
        this.hits = [];
        this.results.replaceChildren();
        this.setSearchStatus(message, "error");
        this.showSql(resp);
    }
    showSql(resp) {
        if (!resp || resp.sql.length === 0) {
            this.sql.hidden = true;
            this.sqlText.textContent = "";
            return;
        }
        this.sql.hidden = false;
        const summary = this.sql.querySelector("summary");
        if (summary)
            summary.textContent = `SQL (${resp.sql.length} statement${resp.sql.length === 1 ? "" : "s"}, ${resp.elapsed_ms} ms)`;
        this.sqlText.textContent = resp.sql.join(";\n\n");
    }
    /** Render hits from their `parts` (text nodes; <mark> for matches). */
    showResults(resp, inField) {
        this.hits = resp.hits;
        const items = resp.hits.map((hit, k) => {
            const li = h("li");
            const btn = h("button", "hit");
            btn.type = "button";
            btn.dataset.hit = String(k);
            const head = h("span", "hit-head");
            head.append(h("span", "hit-title", hit.title || hit.target), h("span", "hit-type", hit.type));
            const snippet = h("span", "hit-snippet");
            snippet.append(renderParts(hit.parts));
            const where = hit.concepts.find(inField);
            const meta = h("span", "hit-id", where ? hit.target : `${hit.target} (not in the field)`);
            btn.append(head, snippet, meta);
            li.append(btn);
            return li;
        });
        this.results.replaceChildren(...items);
        const shown = resp.hits.length;
        const total = resp.total;
        const prefix = this.offline ? "offline: label search only (API not reachable) · " : "";
        const count = total > shown ? `${fmt.format(shown)} of ${fmt.format(total)} hits` : `${fmt.format(shown)} hit${shown === 1 ? "" : "s"}`;
        this.setSearchStatus(`${prefix}${count}${this.offline ? "" : ` · ${resp.elapsed_ms} ms`}`, this.offline ? "offline" : null);
        this.showSql(resp);
    }
    // ------------------------------------------------------------ inspector
    clearInspector() {
        this.inspector.replaceChildren(h("p", "hint", "Click a particle or a result to inspect it."));
    }
    showInspectorLoading(label, id) {
        this.inspector.replaceChildren(this.inspectorHead(label, id, ""), h("p", "hint", "Loading the record…"));
    }
    showInspectorError(label, id, message) {
        this.inspector.replaceChildren(this.inspectorHead(label, id, ""), h("p", "status error", message));
    }
    inspectorHead(label, id, extra) {
        const head = h("header", "inspector-head");
        head.append(h("h2", undefined, label || id), h("p", "node-id", extra ? `${id} · ${extra}` : id));
        return head;
    }
    refList(title, refs, inField) {
        const sec = h("section", "rel");
        sec.append(h("h3", undefined, `${title} (${refs.length})`));
        if (refs.length === 0) {
            sec.append(h("p", "none", "none"));
            return sec;
        }
        const ul = h("ul", "chips");
        for (const r of refs) {
            const li = h("li");
            if (inField(r.id)) {
                const b = h("button", "link", r.label || r.id);
                b.type = "button";
                b.dataset.id = r.id;
                b.title = r.id;
                li.append(b);
            }
            else {
                li.append(h("span", "plain", r.label || r.id));
                li.title = r.id;
            }
            ul.append(li);
        }
        sec.append(ul);
        return sec;
    }
    collapsible(title, count, body, open = false) {
        const d = h("details", "sub");
        d.open = open;
        d.append(h("summary", undefined, `${title} (${count})`));
        if (count === 0)
            d.append(h("p", "none", "none"));
        else
            d.append(body());
        return d;
    }
    showNode(rec, inField, offlineNote) {
        const parts = [];
        parts.push(this.inspectorHead(rec.label, rec.id, [rec.scheme, rec.status].filter(Boolean).join(" · ")));
        if (offlineNote)
            parts.push(h("p", "status offline", offlineNote));
        if (rec.scope_note)
            parts.push(h("p", "scope-note", rec.scope_note));
        const facts = h("dl", "facts");
        const fact = (k, v) => {
            facts.append(h("dt", undefined, k), h("dd", undefined, v));
        };
        fact("Coverage", rec.langs === null ? "unknown (not reconciled)" : `${fmt.format(rec.langs)} Wikipedia language editions`);
        if (!offlineNote)
            fact("Labels", `${fmt.format(rec.labels.length)} in ${fmt.format(rec.n_label_langs)} languages`);
        if (rec.code)
            fact("Code", rec.code);
        parts.push(facts);
        parts.push(this.refList("Broader", rec.broader, inField));
        parts.push(this.refList("Narrower", rec.narrower, inField));
        parts.push(this.refList("Related", rec.related, inField));
        parts.push(this.collapsible("Mappings", rec.mappings.length, () => {
            const ul = h("ul", "rows");
            for (const m of rec.mappings) {
                const li = h("li");
                if (inField(m.id)) {
                    const b = h("button", "link", m.label || m.id);
                    b.type = "button";
                    b.dataset.id = m.id;
                    li.append(b);
                }
                else
                    li.append(h("span", "plain", m.label || m.id));
                li.append(h("span", "meta", ` ${m.id} · ${[m.relation, m.method, m.status].filter(Boolean).join(" · ")}`));
                ul.append(li);
            }
            return ul;
        }, rec.mappings.length > 0 && rec.mappings.length <= 6));
        if (!offlineNote) {
            // Labels grouped by language, collapsed (there can be hundreds).
            parts.push(this.collapsible(`Labels in ${fmt.format(rec.n_label_langs || new Set(rec.labels.map((l) => l.lang)).size)} languages`, rec.labels.length, () => {
                const groups = new Map();
                for (const l of rec.labels)
                    (groups.get(l.lang) ?? groups.set(l.lang, []).get(l.lang)).push(l);
                const dl = h("dl", "labels");
                for (const lang of [...groups.keys()].sort()) {
                    dl.append(h("dt", undefined, lang));
                    const dd = h("dd");
                    groups.get(lang).forEach((l, k) => {
                        if (k > 0)
                            dd.append(document.createTextNode(" · "));
                        dd.append(h("span", l.kind === "pref" ? "pref" : "alt", l.text));
                        if (l.kind && l.kind !== "pref")
                            dd.append(h("span", "meta", ` (${l.kind})`));
                    });
                    dl.append(dd);
                }
                return dl;
            }));
            parts.push(this.collapsible("Documents", rec.documents.length, () => {
                const ul = h("ul", "rows docs");
                for (const d of rec.documents) {
                    const li = h("li");
                    const href = safeHref(d.url);
                    if (href) {
                        const a = h("a", undefined, d.title || d.id);
                        a.href = href;
                        a.target = "_blank";
                        a.rel = "noopener noreferrer";
                        li.append(a);
                    }
                    else
                        li.append(h("span", "plain", d.title || d.id));
                    li.append(h("span", "meta", ` · ${[d.lang, d.license || "license unknown"].filter(Boolean).join(" · ")}`));
                    if (d.excerpt)
                        li.append(h("p", "excerpt", d.excerpt));
                    const src = h("p", "meta");
                    src.append(document.createTextNode(href ? "Source: " : "Source (not a web link): "));
                    src.append(h("span", "mono", href ?? d.url ?? d.id));
                    if (d.sha512)
                        src.append(document.createTextNode(` · sha512 ${d.sha512.slice(0, 16)}…`));
                    src.title = d.sha512;
                    li.append(src);
                    ul.append(li);
                }
                return ul;
            }, rec.documents.length > 0 && rec.documents.length <= 3));
            parts.push(this.collapsible("Claims", rec.claims.length, () => {
                const ul = h("ul", "rows");
                for (const c of rec.claims) {
                    const li = h("li");
                    li.append(h("span", "plain", `${c.predicate_label || c.predicate} → ${c.object_label || c.object}`));
                    li.append(h("span", "meta", ` ${[c.epistemic.replace(/^epistemic\//, ""), c.rank].filter(Boolean).join(" · ")}`));
                    li.title = `${c.subject} ${c.predicate} ${c.object}${c.source ? `\nsource ${c.source}` : ""}`;
                    ul.append(li);
                }
                return ul;
            }));
        }
        parts.push(this.collapsible("Neighbours", rec.neighbors.length, () => {
            const ul = h("ul", "rows");
            for (const nb of rec.neighbors) {
                const li = h("li");
                if (inField(nb.id)) {
                    const b = h("button", "link", nb.label || nb.id);
                    b.type = "button";
                    b.dataset.id = nb.id;
                    li.append(b);
                }
                else
                    li.append(h("span", "plain", nb.label || nb.id));
                li.append(h("span", "meta", ` ${nb.score.toFixed(2)}${nb.model ? ` · ${nb.model}` : ""}`));
                ul.append(li);
            }
            return ul;
        }));
        if (!offlineNote) {
            parts.push(this.collapsible("Provenance", rec.provenance.length, () => {
                const ul = h("ul", "rows");
                for (const p of rec.provenance) {
                    const li = h("li");
                    li.append(h("span", "mono", p.source));
                    li.append(h("span", "meta", ` · ${p.kind}${p.sha512 ? ` · sha512 ${p.sha512.slice(0, 16)}…` : ""}`));
                    li.title = p.sha512;
                    ul.append(li);
                }
                return ul;
            }));
        }
        this.inspector.replaceChildren(...parts);
    }
    // ------------------------------------------------------------ lens and key
    setLens(lens) {
        for (const radio of document.querySelectorAll('input[name="lens"]'))
            radio.checked = radio.value === lens;
    }
    setSemantic(on) {
        this.semantic.checked = on;
    }
    /** The key always explains the marks of the current lens. */
    renderKey(lens, legend, showSemantic) {
        const rows = [];
        const row = (mark, text) => {
            const r = h("div", "key-row");
            if (mark)
                r.append(mark);
            r.append(h("span", undefined, text));
            return r;
        };
        if (lens === "structure") {
            rows.push(h("p", "key-title", "Structure"));
            rows.push(row(swatch("dot", "var(--ink)"), "concept · size ∝ descendants + documents"));
            rows.push(row(swatch("dot", "var(--accent)"), "search hit / hover"));
            rows.push(row(swatch("selected", "var(--accent-2)"), "selected (always labelled)"));
            rows.push(row(swatch("line", "var(--ink)", 0.4), "broader (hierarchy)"));
            rows.push(row(swatch("line", "var(--ink)", 0.2), showSemantic ? "related · mapping · semantic" : "related · mapping"));
            rows.push(h("p", "key-note", "Domains: cluster + label at its centre, not colour."));
        }
        else {
            rows.push(h("p", "key-title", "Coverage: Wikipedia language editions"));
            const bar = h("div", "ramp");
            bar.setAttribute("role", "img");
            bar.setAttribute("aria-label", `Sequential scale from ${legend.min} to ${legend.max} language editions, log scale`);
            for (const c of legend.ramp) {
                const step = h("span", "ramp-step");
                step.style.background = c;
                bar.append(step);
            }
            const ends = h("div", "ramp-ends");
            ends.append(h("span", undefined, fmt.format(legend.min)), h("span", "ramp-scale", "log scale"), h("span", undefined, fmt.format(legend.max)));
            rows.push(bar, ends);
            rows.push(row(swatch("hollow", "var(--muted)"), `no data (${fmt.format(legend.total - legend.known)} of ${fmt.format(legend.total)})`));
            rows.push(row(swatch("ring", "var(--ink)"), "search hit / hover (ink ring)"));
            rows.push(row(swatch("selected", "var(--accent-2)"), "selected (always labelled)"));
        }
        this.key.replaceChildren(...rows);
    }
    keyRect() {
        return this.key.getBoundingClientRect();
    }
    // ------------------------------------------------------------ tooltip
    showTooltip(x, y, title, lines, fieldW, fieldH) {
        const tip = this.tooltip;
        tip.replaceChildren(h("strong", undefined, title), ...lines.map((l) => h("span", undefined, l)));
        tip.hidden = false;
        const w = tip.offsetWidth;
        const ht = tip.offsetHeight;
        let left = x + 14;
        let top = y + 14;
        if (left + w > fieldW - 8)
            left = Math.max(8, x - w - 14);
        if (top + ht > fieldH - 8)
            top = Math.max(8, y - ht - 14);
        tip.style.left = `${left}px`;
        tip.style.top = `${top}px`;
    }
    hideTooltip() {
        this.tooltip.hidden = true;
    }
    // ------------------------------------------------------------ audit
    auditIsOpen() {
        return this.audit.open;
    }
    showAuditLoading() {
        this.auditBody.replaceChildren(h("p", "hint", "Loading the audit…"));
    }
    showAuditError(message) {
        this.auditBody.replaceChildren(h("p", "status error", message));
    }
    showAudit(a, offline, inField) {
        const out = [];
        if (offline)
            out.push(h("p", "status offline", "offline: computed from the loaded graph (API not reachable)"));
        else if (a.generated_at)
            out.push(h("p", "meta", `Generated ${a.generated_at}`));
        const idCell = (id, label) => {
            if (inField(id)) {
                const b = h("button", "link", label || id);
                b.type = "button";
                b.dataset.id = id;
                b.title = id;
                return b;
            }
            const s = h("span", undefined, label || id);
            s.title = id;
            return s;
        };
        const table = (caption, head, rows, numeric) => {
            const wrap = h("div", "table-wrap");
            const t = h("table");
            t.append(h("caption", undefined, caption));
            const thead = h("thead");
            const tr = h("tr");
            head.forEach((c, k) => {
                const th = h("th", numeric[k] ? "num" : undefined, c);
                th.scope = "col";
                tr.append(th);
            });
            thead.append(tr);
            const tbody = h("tbody");
            for (const r of rows) {
                const row = h("tr");
                r.forEach((c, k) => {
                    const td = h("td", numeric[k] ? "num" : undefined);
                    if (typeof c === "string")
                        td.textContent = c;
                    else
                        td.append(c);
                    row.append(td);
                });
                tbody.append(row);
            }
            t.append(thead, tbody);
            wrap.append(t);
            return wrap;
        };
        const n = (v) => (v === null ? "—" : fmt.format(Math.round(v * 10) / 10));
        if (a.domains.length > 0) {
            out.push(table("Domains (langs: Wikipedia language editions per concept)", ["Domain", "Concepts", offline ? "Known" : "Reconciled", "Docs", "Median", "Min"], a.domains.map((d) => [idCell(d.id, d.label), n(d.concepts), n(d.reconciled), n(d.docs), n(d.median_langs), d.min_langs_id ? idCell(d.min_langs_id, n(d.min_langs)) : n(d.min_langs)]), [false, true, true, true, true, true]));
        }
        if (a.thinnest.length > 0) {
            out.push(table("Thinnest coverage", ["Concept", "Langs"], a.thinnest.map((t) => [idCell(t.id, t.label), n(t.langs)]), [false, true]));
        }
        if (a.regions.length > 0) {
            out.push(table("Regions (where facet)", ["Region", "Tagged"], a.regions.map((r) => [idCell(r.id, r.label), n(r.tagged)]), [false, true]));
        }
        if (a.label_languages.length > 0) {
            out.push(table("Label languages", ["Language", "Concepts"], a.label_languages.map((l) => [l.lang, n(l.concepts)]), [false, true]));
        }
        if (a.notes.length > 0) {
            const ul = h("ul", "notes");
            for (const note of a.notes)
                ul.append(h("li", undefined, note));
            out.push(ul);
        }
        if (out.length === 0)
            out.push(h("p", "none", "The audit is empty."));
        this.auditBody.replaceChildren(...out);
    }
}
//# sourceMappingURL=ui.js.map