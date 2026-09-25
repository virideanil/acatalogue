// Colours come from CSS custom properties: style.css is the single source of truth.
// The page follows prefers-color-scheme until the toggle stamps data-theme on :root,
// which then wins in both directions.
const STORAGE_KEY = "acatalogue.theme";
function prop(style, name, fallback) {
    const v = style.getPropertyValue(name).trim();
    return v.length > 0 ? v : fallback;
}
/** Read the current theme tokens from :root. */
export function readTheme() {
    const style = getComputedStyle(document.documentElement);
    const ramp = prop(style, "--coverage-ramp", "#6da7ec #0d366b")
        .split(/[\s,]+/)
        .filter((s) => s.length > 0);
    return {
        name: prop(style, "--theme-name", "light") === "dark" ? "dark" : "light",
        surface: prop(style, "--surface", "#f4eedf"),
        ink: prop(style, "--ink", "#2c2d29"),
        ink2: prop(style, "--ink-2", "#5b5a52"),
        muted: prop(style, "--muted", "#8a877c"),
        hairline: prop(style, "--hairline", "rgba(44,45,41,0.14)"),
        accent: prop(style, "--accent", "#2a78d6"),
        accent2: prop(style, "--accent-2", "#eb6834"),
        ramp,
        font: prop(style, "--font", 'system-ui, -apple-system, "Segoe UI", sans-serif'),
    };
}
const darkQuery = () => window.matchMedia("(prefers-color-scheme: dark)");
/** The theme in effect: an explicit data-theme stamp, else the OS preference. */
export function effectiveTheme() {
    const stamp = document.documentElement.getAttribute("data-theme");
    if (stamp === "light" || stamp === "dark")
        return stamp;
    return darkQuery().matches ? "dark" : "light";
}
function store(value) {
    try {
        if (value === null)
            window.localStorage.removeItem(STORAGE_KEY);
        else
            window.localStorage.setItem(STORAGE_KEY, value);
    }
    catch {
        // Storage can be unavailable (private windows, blocked site data); the stamp still applies.
    }
}
/** Stamp (or clear, with null) the theme on :root and remember the choice. */
export function setTheme(value) {
    if (value === null)
        document.documentElement.removeAttribute("data-theme");
    else
        document.documentElement.setAttribute("data-theme", value);
    store(value);
}
/** Flip the effective theme; returns the new one. */
export function toggleTheme() {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    setTheme(next);
    return next;
}
/** Re-apply a remembered choice (called once at startup). */
export function restoreTheme() {
    let saved = null;
    try {
        saved = window.localStorage.getItem(STORAGE_KEY);
    }
    catch {
        saved = null;
    }
    if (saved === "light" || saved === "dark")
        document.documentElement.setAttribute("data-theme", saved);
}
/** Call `onChange` whenever the effective theme can have changed (OS or toggle). */
export function watchTheme(onChange) {
    darkQuery().addEventListener("change", onChange);
    new MutationObserver(onChange).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
}
//# sourceMappingURL=theme.js.map