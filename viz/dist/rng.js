// Seeded randomness for layout. Math.random() is never used: the same data must give
// the same initial layout, so every random draw is derived from a node id.
/** FNV-1a 32-bit hash over UTF-16 code units. */
export function hashString(s) {
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) {
        h ^= s.charCodeAt(i);
        h = Math.imul(h, 0x01000193);
    }
    return h >>> 0;
}
/** mulberry32: a small seeded PRNG returning floats in [0, 1). */
export function mulberry32(seed) {
    let a = seed >>> 0;
    return () => {
        a = (a + 0x6d2b79f5) >>> 0;
        let t = a;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}
/** A PRNG seeded from an id (plus an optional salt for independent streams). */
export function rngFor(id, salt = 0) {
    return mulberry32(hashString(id) ^ Math.imul(salt + 1, 0x9e3779b1));
}
//# sourceMappingURL=rng.js.map