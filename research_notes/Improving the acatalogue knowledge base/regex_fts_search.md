# Search engineering for acatalogue's SQL grepper: regex-to-trigram extraction, FTS5 tokenization, multilingual matching, ranking

*How the evidence was gathered.* Web sources are cited inline. Findings tagged **Exp A–F** come from experiments run in this session on **Python 3.11.15 + SQLite 3.45.1**, the versions acatalogue targets. They ran against `data/acatalogue.sqlite` (72.3 MB), which was opened read-only and never modified. The scripts are in the session scratchpad at `/tmp/claude-0/-home-user-acatalogue/0c6b5ec4-d312-5493-9173-1d9be46979db/scratchpad/`, and that directory may not persist.

- `exp1.py` (Exp A) probes tokenizer options, case folding and LIKE/GLOB.
- `exp2.py` (Exp B) gathers counts, timings and edge cases on the real data.
- `exp3.py` (Exp C) is a Cox-style extractor with a false-negative fuzz test.
- `exp4.py` (Exp D) measures tokenizer precision and recall, plus index sizes.
- Exp E and Exp F are inline Bash checks recorded in this session: source-tag diffs, rowid alignment, and `remove_diacritics` on Turkish.

Timings are best-of-3 on this container and indicate orders of magnitude only. The code cited is `acatalogue/grep.py`, `acatalogue/db.py`, `acatalogue/schema.sql` and `acatalogue/build.py` at commit `0f9b65c`.

## 1. How is an AND/OR trigram query computed from a regex (Cox 2012)? How do codesearch, zoekt and pg_trgm implement or adapt it, and when do they give up?

### Takeaway
Cox's method walks the regex syntax tree from the bottom up. For each node it computes five facts: `emptyable`, `exact`, `prefix`, `suffix` and `match`. It then folds the string sets into an AND/OR query over trigrams. **Every** matching document must satisfy that query, and the real regex verifies each candidate. The three systems use the method differently:

- **codesearch** implements it faithfully, with small caps (7 exact strings, 20 prefix/suffix strings, 100-rune classes).
- **zoekt** uses a much cruder "extract literals" version.
- **pg_trgm** uses a more precise automaton-based variant with hard state and arc limits.

All three degrade to "match everything, then scan" whenever they cannot prove a requirement of at least 3 characters. A Python port over `re._parser` found no false negatives on acatalogue's labels (Exp C) and prefiltered 348/400 random regexes, against 209/400 for the current rule.

### Cited Findings
- **The architecture is a filter followed by verification.** Code Search built a trigram index, would "run this query against the trigram index to identify a set of candidate documents and then run the full regular expression search against only those documents". Regex matches "do not always line up nicely on word boundaries, so the inverted index cannot be based on words". — [Cox, "Regular Expression Matching with a Trigram Index" (2012)](https://swtch.com/~rsc/regexp/regexp4.html)
- **Construction rules.** — [Cox](https://swtch.com/~rsc/regexp/regexp4.html)
  - `''` has emptyable=true, exact={''}, prefix=suffix={''}, match=ANY.
  - A single character `c` has exact={c}, prefix=suffix={c}, match=ANY.
  - `e1|e2` takes the union of exact, prefix and suffix, and match = match1 OR match2.
  - `e1e2` has exact = exact1×exact2 if both are known. prefix = exact1×prefix2 if exact1 is known; otherwise prefix1 ∪ prefix2 if e1 is emptyable, else prefix1. Suffix is symmetric, and match = match1 AND match2.
  - `e?` has exact = exact(e) ∪ {''}. `e*` has exact unknown, prefix=suffix={''}, match=ANY.
  - `e+` keeps prefix, suffix and match, and makes exact unknown.
- **Trigram extraction.** `trigrams(s)` is ANY when |s| < 3. Otherwise it is the AND of every 3-character substring, and a set of strings maps to the OR over its members. — [Cox](https://swtch.com/~rsc/regexp/regexp4.html)
- **Simplification.** — [Cox](https://swtch.com/~rsc/regexp/regexp4.html)
  - *Information-saving* steps, allowed at any point: match := match AND trigrams(prefix|suffix|exact).
  - *Information-discarding* steps: drop redundant prefixes/suffixes, trim long prefix/suffix strings, and set exact=unknown when it grows too large.
  - Boolean simplification, e.g. "abc OR (abc AND def)" becomes "abc".
- **Reported numbers.** The index is about 20% of the indexed files: the Linux 3.1.3 sources (420 MB) produced a 77 MB index. Searching `hello world` narrowed 36,972 files to 25 and ran about 100× faster. — [Cox](https://swtch.com/~rsc/regexp/regexp4.html)
- **codesearch caps and their rationale.** — [google/codesearch index/regexp.go](https://github.com/google/codesearch/blob/master/index/regexp.go)
  - `maxExact = 7`, with the comment "…it helps to avoid ridiculous alternations if maxExact is sized so that 3 case-insensitive letters triggers a flush".
  - `maxSet = 20`, with the comment "…useful for maxSet to be at least 2³ = 8 so that we can exactly represent a case-insensitive abc by the set {abc, abC, aBc, aBC, Abc, AbC, ABc, ABC}".
  - A class spanning more than 100 runes becomes `anyChar()` ("If the class is too large, it's okay to overestimate").
  - A single-letter case-folded literal is rewritten into a character class of all its `unicode.SimpleFold` variants.
- **codesearch's soundness rule.** `andTrigrams` returns the query unchanged when `t.minLen() < 3`: "If there is a short string, we can't guarantee that any trigrams must be present, so use ALL." — [regexp.go](https://github.com/google/codesearch/blob/master/index/regexp.go)
- **Other codesearch details.** — [regexp.go](https://github.com/google/codesearch/blob/master/index/regexp.go)
  - `simplify` moves exact into match when `len(exact) > maxExact || (minLen >= 3 && force) || minLen >= 4`.
  - At a concatenation boundary, `concat` ANDs in the trigrams of cross(x.suffix, y.prefix) when both sets are ≤ maxSet and the length sum is ≥ 3.
  - `OpStar` gives `anyMatch()`, `OpQuest` gives alternate(sub, empty), and `OpPlus` keeps prefix/suffix but drops exact.
  - Trigrams are taken as `tt[i : i+3]` slices of Go strings, so they are **byte** (UTF-8) trigrams.
- **zoekt's index.** zoekt keeps a *positional* trigram index. A substring search picks the two rarest trigrams and checks their distance. Offsets are in runes, with a rune-to-byte map stored "every 100 runes". The index is about 3× the corpus size. Case-insensitive search looks up "all the different case variants" and then compares without regard to case. — [zoekt design.md](https://github.com/sourcegraph/zoekt/blob/main/doc/design.md)
  - Its example: `(Path|PathFragment).*=.*/usr/local` becomes `(AND (OR substr:"Path" substr:"PathFragment") substr:"/usr/local")`.
- **zoekt's conversion rules.** `regexpToMatchTreeRecursive` works as follows. — [zoekt index/eval.go](https://github.com/sourcegraph/zoekt/blob/main/index/eval.go); `ngramSize = 3` in [index/shard_builder.go](https://github.com/sourcegraph/zoekt/blob/main/index/shard_builder.go)
  - Literals of at least `minTextSize` runes become substring matches.
  - Capture, `+` and `{n,}` with n ≥ 1 pass through to their child.
  - Concatenation becomes AND, dropping children that would need brute force.
  - An alternation with **any** brute-force branch becomes brute force as a whole.
  - Everything else, including character classes and `*`, becomes `bruteForceMatchTree`.
- **pg_trgm basics.** Trigrams are lower-cased in a default build. Each word is padded with "two spaces prefixed and one space suffixed", and non-alphanumerics are ignored. LIKE/ILIKE became indexable in 9.1 and `~`/`~*` in 9.3. "A pattern with no extractable trigrams will degenerate to a full-index scan." The current docs are for PostgreSQL 18. — [PostgreSQL pg_trgm docs](https://www.postgresql.org/docs/current/pgtrgm.html). Regex indexing is credited "(Alexander Korotkov)". — [PostgreSQL 9.3 release notes](https://www.postgresql.org/docs/release/9.3.0/)
- **pg_trgm's regex algorithm.** — [trgm_regexp.c](https://github.com/postgres/postgres/blob/master/contrib/pg_trgm/trgm_regexp.c)
  - The regex engine's NFA, whose arcs are labelled with "colors", is turned into an expanded graph. Each state there carries "a prefix identifying the last two characters (colors…)", and each arc carries "a trigram that must be present".
  - Color trigrams are then expanded into ordinary trigrams, and the graph is packed and evaluated by a breadth-first search over the trigrams present.
  - Limits: `MAX_EXPANDED_STATES` 128, `MAX_EXPANDED_ARCS` 1024, `MAX_TRGM_COUNT` 256, `WISH_TRGM_PENALTY` 16, `COLOR_COUNT_LIMIT` 256.
  - On overflow "we give up and simply mark any states not yet processed as final states". Color trigrams are dropped by penalty, but never in a way that merges the initial and final states.
  - Soundness: "If a string matches the regex, then it must match the logical expression on trigrams… false positives are removed via recheck."
  - Case: "In IGNORECASE mode, we can ignore uppercase characters", on the assumption that REG_ICASE colors contain both cases.
- **Exp C, the Python port.** The Cox/codesearch rules were ported to the tree from Python's `re._parser`:
  - LITERAL, IN (≤ 30 members), ANY, BRANCH, SUBPATTERN, ATOMIC_GROUP and MAX/MIN/POSSESSIVE_REPEAT are handled.
  - AT, ASSERT and ASSERT_NOT are treated as zero-width. GROUPREF and GROUPREF_EXISTS are treated as "any".
  - It uses character trigrams and caps of 7 and 20, and emits FTS5 MATCH strings built from double-quoted phrases.

  **Results.** It ran against a key-folded trigram index of all 121,717 labels (see §3). Over 400 random regexes generated from real label fragments, it produced **0 false-negative patterns**. The fragments used literals, `(?i)`, alternation, optional groups, classes, bounded repeats, lookarounds and backreferences.
  - A prefilter was available for **348/400** patterns, against **209/400** for acatalogue's current `required_literal` rule.
  - The candidate set had a median of 2 rows (p90 197, max 2,149).
  - All full scans took 11.53 s in total; prefilter plus verify took 0.10 s on the prefiltered subset.
  - Sample translations: `(?:colou?r|hue)s?` becomes `("hue" OR ("colo" AND ("lor" OR "our")))`. `(?i)istanbul` becomes an AND of `"ista"`, `"tan"`, `"anb"`, `"nbu"`, `"bul"`. `东京|東京都` becomes a full scan, because one branch is 2 characters.
  - — Exp C (`exp3.py`)

### Inferences
- **The three systems span a precision-versus-complexity range.**
  - zoekt extracts literals only and gives up on any alternation that contains a non-literal branch.
  - Cox/codesearch adds exact sets, small classes, case variants, and prefix/suffix reasoning across concatenations.
  - pg_trgm is the most precise, but it needs the regex engine's NFA, which Python's `re` does not expose.
- **For acatalogue, Cox on the sre parse tree is the right level.** The grepper already imports `re._parser`, and Exp C shows real gains without false negatives.
- **The rule for giving up is common to all three.** If the final query is ANY, or any cap is exceeded, scan everything.
  - Dropping an AND conjunct is always safe. Dropping a single OR branch is **never** safe; instead the whole OR must become ANY.
  - A string shorter than 3 characters must never be emitted.
- **Byte trigrams and character trigrams behave differently.** Because codesearch indexes bytes, a single CJK character (3 UTF-8 bytes) is indexable there. FTS5 trigrams are characters, so CJK needs 3 characters. This is a structural reason why 2-character CJK searches cannot use FTS5's trigram index.
- **The prototype emits overlapping pieces rather than whole literals.** It produced `"ista" AND "anb" …` instead of `"istanbul"` because it builds exact sets character by character. An implementation should first merge each run of consecutive LITERAL nodes into one exact string, so that each run becomes a single, stronger FTS5 phrase.

### Gaps
- pg_trgm's regex support was not benchmarked. The Cox article's case-insensitive timing figures were not verified verbatim, so they are not reported.
- 400 fuzz patterns drawn from 20 templates are evidence, not proof. A larger property-based test belongs in the test suite (see §7).

## 2. SQLite FTS5 trigram tokenizer and related behaviour: options and versions, LIKE/GLOB, short patterns, index size, REGEXP, and safe AND/OR MATCH syntax

### Takeaway
The trigram tokenizer has existed since 3.34.0, with `case_sensitive`. `remove_diacritics` was added quietly in **3.45.0**. The main behaviours:

- A full-text query shorter than 3 characters matches nothing.
- LIKE/GLOB are accelerated by being turned into ANDed double-quoted phrases, one per run of at least 3 non-wildcard characters. SQLite's core then **re-checks** each row with the real LIKE/GLOB.
- On labels the index costs about 3× the raw text.

Nothing in SQLite accelerates REGEXP. MATCH is the only way to express the AND/OR prefilter, and it is safe provided every phrase has at least 3 characters and embedded `"` are doubled.

### Cited Findings
- **Versions and history.**
  - "Enhanced FTS5 to support trigram indexes" appears in 3.34.0. — [SQLite changes](https://sqlite.org/changes.html)
  - `case_sensitive` and the LIKE/GLOB pattern hook are already in the 3.34.0 source. — Exp E, [fts5_tokenize.c @ version-3.34.0](https://github.com/sqlite/sqlite/blob/version-3.34.0/ext/fts5/fts5_tokenize.c)
  - The trigram `remove_diacritics` option is absent at version-3.43.0 and version-3.44.0 and present at version-3.45.0. The release notes do not mention it. — Exp E, [fts5_tokenize.c @ version-3.45.0](https://github.com/sqlite/sqlite/blob/version-3.45.0/ext/fts5/fts5_tokenize.c), [changes](https://sqlite.org/changes.html)
  - The latest release is 3.53.4 (2026-07-24). Releases 3.46–3.53 list only FTS5 fixes and features, such as `locale=1`, `fts5_tokenizer_v2` and `contentless_unindexed` in 3.47.0, `insttoken` in 3.48.0, and better FTS5 error messages in 3.51.0. None of them changes the trigram tokenizer. — [changes](https://sqlite.org/changes.html)
- **Other feature versions acatalogue may need.** — [changes](https://sqlite.org/changes.html); categories check: Exp E, [fts5_tokenize.c @ version-3.25.0](https://github.com/sqlite/sqlite/blob/version-3.25.0/ext/fts5/fts5_tokenize.c)

  | Version | Feature |
  |---|---|
  | 3.10.0 | LIKE/GLOB/REGEXP constraints on virtual tables |
  | 3.11.0 | `detail=` |
  | 3.21.0 | `fts5vocab` 'instance' |
  | 3.22.0 | `^` initial token |
  | 3.25.0 | unicode61 `categories` (absent in the 3.24.0 source, present in 3.25.0) |
  | 3.27.0 | `remove_diacritics=2` |
  | 3.43.0 | contentless-delete |
  | 3.44.0 | `PRAGMA integrity_check` covers FTS3/4/5 |
  | 3.45.0 | `tokendata` |
  | 3.45.1 | integrity_check works on read-only DBs that contain FTS5 |

- **Documentation, verbatim.** — [FTS5 §4.3.4 The Trigram Tokenizer](https://sqlite.org/fts5.html)
  - `case_sensitive`: "If it is set to 1, then matching is case sensitive. Otherwise… case insensitive".
  - `remove_diacritics` "may only be set to 1 if the case_sensitive options is set to 0".
  - "Unless the remove_diacritics option is set, FTS5 tables that use the trigram tokenizer also support indexed GLOB and LIKE pattern matching." "If… case_sensitive option set to 1, it may only index GLOB queries, not LIKE."
  - "Substrings consisting of fewer than 3 unicode characters do not match any rows when used with a full-text query. If a LIKE or GLOB pattern does not contain at least one sequence of non-wildcard unicode characters, FTS5 falls back to a linear scan of the entire table."
  - "If the FTS5 table is created with the detail=none or detail=column option specified, full-text queries may not contain any tokens longer than 3 unicode characters. LIKE and GLOB pattern matching may be slightly slower, but still works."
  - "The index cannot be used to optimize LIKE patterns if the LIKE operator has an ESCAPE clause."
- **What the source code shows.**
  - `sqlite3Fts5TokenizerPattern` gives **GLOB** when `case_sensitive=1` and **LIKE** when `case_sensitive=0`, where the planner also accepts GLOB. It gives **NONE** whenever `remove_diacritics` is set. — [fts5_tokenize.c](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_tokenize.c), [fts5_main.c](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_main.c)
  - In `xBestIndex`, LIKE/GLOB constraints receive an `argvIndex` but `omit` is **not** set, unlike MATCH. The SQLite core therefore re-evaluates LIKE/GLOB on every candidate row, so FTS5 itself uses prefilter plus recheck. — [fts5_main.c](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_main.c)
  - `sqlite3Fts5ExprPattern` splits a pattern at wildcards: `_ %` for LIKE, and `* ? [...]` for GLOB, whose bracket expressions are skipped. It emits each run of at least 3 characters as `"run"`, doubling any embedded `"`. The runs are ANDed implicitly. For `detail!=full` it ANDs the trigrams instead of forming phrases. — [fts5_expr.c](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_expr.c)
  - The tokenizer folds each code point with `sqlite3Fts5UnicodeFold(iCode, iFoldParam)` and skips any code point that folds to 0, which happens to combining marks when `remove_diacritics` is set. `remove_diacritics 1` on a trigram table uses fold mode **2** (the "complex" Latin removal). — [fts5_tokenize.c](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_tokenize.c)
- **Exp A results on 3.45.1.**
  - `trigram`, `trigram case_sensitive 1` and `trigram remove_diacritics 1` are all accepted. Setting both to 1 fails with "error in tokenizer constructor".
  - `MATCH '"ab"'` and `MATCH '"東京"'` return **no rows and no error**.
  - `LIKE '%st%'`, which has no run of 3 or more, still shows `SCAN tri VIRTUAL TABLE INDEX 0:L0` in EXPLAIN QUERY PLAN, although FTS5 falls back to a scan. **The plan text does not prove the index was used.**
  - On a `case_sensitive 1` table, LIKE is planned as `INDEX 0:` (not indexed) and GLOB as `G0`. On `remove_diacritics 1`, neither is indexed. `LIKE … ESCAPE` is not indexed.
  - `LIKE '%İSTANBUL%'` returns only `İstanbul`, not `istanbul`. This is the core LIKE semantics.
- **The core LIKE semantics.** "SQLite only understands upper/lower case for ASCII characters by default. The LIKE operator is case sensitive by default for unicode characters that are beyond the ASCII range." — [SQLite expressions](https://sqlite.org/lang_expr.html)
- **Index size in the built DB** (`dbstat`, Exp B):

  | Object | Size |
  |---|---|
  | `label` table | 24.1 MB |
  | `label_tri_data` | 12.44 MB (+ `label_tri_docsize` 1.93 MB) |
  | `label_fts_data` | 3.06 MB (+ docsize 1.95 MB) |
  | `passage` table | 1.24 MB |
  | `passage_tri_data` | 3.08 MB |

- **Fresh builds over the 3.14 MB of UTF-8 label text** (after `optimize` and `VACUUM`, Exp D):

  | Variant | Size |
  |---|---|
  | trigram, detail=full, with content copy | 13.31 MB |
  | trigram, detail=column | 13.22 MB |
  | trigram, detail=none | 9.39 MB |
  | contentless key-folded trigram, `case_sensitive 1` | 9.02 MB |
  | unicode61, contentless | 3.56 MB |

  For comparison, codesearch reported an index of about 20% of the source ([Cox](https://swtch.com/~rsc/regexp/regexp4.html)) and zoekt about 3× the corpus ([zoekt design](https://github.com/sourcegraph/zoekt/blob/main/doc/design.md)).
- **Dropping the size table.** "In order to save space, this backing table may be omitted by setting the columnsize option to zero". The table feeds `xColumnSize`, which bm25 uses. — [FTS5 §4.5](https://sqlite.org/fts5.html)
- **SQLite has no REGEXP implementation by default.** "The REGEXP operator is a special syntax for the regexp() user function. No regexp() user function is defined by default…". — [SQLite expressions](https://sqlite.org/lang_expr.html)
  - FTS5's `xBestIndex` consumes only MATCH/rank, LIKE/GLOB and rowid constraints, never REGEXP. — [fts5_main.c](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_main.c)
  - SQLite's own `ext/misc/regexp.c` is a "compact but reasonably efficient regular-expression matcher for posix extended regular expressions". It is included in CLI builds since 3.36.0, and 3.39.1 fixed its "initial-prefix optimization", which is a scan-time optimization rather than an index. — [regexp.c](https://github.com/sqlite/sqlite/blob/master/ext/misc/regexp.c), [changes](https://sqlite.org/changes.html)
- **Safe query syntax.**
  - Double-quoted strings escape an embedded `"` by doubling it. Barewords are restricted to non-ASCII characters, ASCII letters and digits, `_` and U+001A. Precedence is NOT > AND > OR, and parentheses are allowed. — [FTS5 §3 query syntax](https://sqlite.org/fts5.html)
  - The maximum expression depth is `SQLITE_FTS5_MAX_EXPR_DEPTH 256`. — [fts5_expr.c](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_expr.c)
  - Exp B: `'"a*b(c) NEAR"'` matched literally.
  - Exp B: `'"ista" AND "ul"'` → **0 rows**, and `'"ul" OR "zzz"'` → **0 rows**. A phrase of 1–2 characters anywhere in the expression **silently removes rows**.

### Inferences
- **Use MATCH, not LIKE/GLOB, for the regex prefilter.** LIKE/GLOB can only express a conjunction of literal runs, while MATCH expresses OR. In both cases the verification step, Python `re`, is what makes the results exact.
- **Neither SQLite path matches Python's case-insensitivity.** MATCH on the default trigram table uses SQLite's Unicode 6.1 fold, and the LIKE recheck folds ASCII only. Both differ from Python `re.IGNORECASE` (§3).
- **`detail=none` is not worth it here.** It saves about 30% on labels (13.31 → 9.39 MB), but it forbids phrases longer than 3 characters. Substring mode would then need an AND of trigrams plus Python verification, and at a 72 MB database the saving does not justify that.
- **`detail=column` saves almost nothing** for single-column trigram tables (−0.7%).
- **`columnsize=0` is a cheap win** on trigram tables that are never ranked with bm25, which is all of them in acatalogue. It saves about 1.9 MB for labels.
- **`EXPLAIN QUERY PLAN` shows `L0` even when FTS5 scans.** The grepper must decide and report index use itself (a run of at least 3 characters, or a non-ANY query), not infer it from the plan.

### Gaps
- There is no official changelog entry for the trigram `remove_diacritics` option. The 3.45.0 date comes from source tags only.
- Size figures are specific to this corpus of many short labels. The overhead per row (docsize, segment structure) weighs more here than it would for long documents.

## 3. Correctness pitfalls when a trigram prefilter guards Python `re`: case folding, normalization, and guaranteeing no false negatives

### Takeaway
A prefilter is sound only if all three conditions hold:

- (a) The index is built from exactly the string that the regex is run on.
- (b) The query is derived with the same folding as the index.
- (c) No requirement shorter than 3 characters is ever emitted.

acatalogue's current rule for case-sensitive regexes satisfies these conditions. However, SQLite's fold (Unicode 6.1 CaseFolding, BMP plus Deseret only) differs from Python's `re.IGNORECASE` (Unicode 14 simple lowercase plus extra equivalences) in **402 equivalence classes**, including Turkish I/İ/ı, Cherokee, Georgian Mtavruli and Adlam. **Today's substring mode** therefore misses rows that its own highlighter and `(?i)` regexes treat as matches. One such needle missed 155 rows (Exp B). A length-preserving key fold computed in Python, indexed with `trigram case_sensitive 1`, removes the mismatch entirely.

### Cited Findings
- **Python's IGNORECASE extras.** "When the Unicode patterns [a-z] or [A-Z] are used in combination with the IGNORECASE flag, they will match the 52 ASCII letters and 4 additional non-ASCII letters: 'İ' (U+0130…), 'ı' (U+0131…), 'ſ' (U+017F…) and 'K' (U+212A, Kelvin sign)." — [Python 3.11 re docs](https://docs.python.org/3.11/library/re.html)
- **How CPython 3.11 compiles an IGNORECASE literal.** It uses the simple lowercase (`_sre.unicode_tolower`) plus the table `re._casefix._EXTRA_CASES`, which holds equivalences such as i↔ı, s↔ſ and µ↔μ. — [CPython Lib/re/_casefix.py](https://github.com/python/cpython/blob/3.11/Lib/re/_casefix.py), [Lib/re/_compiler.py](https://github.com/python/cpython/blob/3.11/Lib/re/_compiler.py); behaviour confirmed in Exp A.
- **How CPython checks ranges under IGNORECASE.** A range tests both `ch` (already lower-cased) and `sre_upper_unicode(ch)`. — [CPython Modules/_sre/sre_lib.h](https://github.com/python/cpython/blob/3.11/Modules/_sre/sre_lib.h)
- **`str.casefold()` is a third, different semantics.** It is full folding: "the German lowercase letter 'ß' is equivalent to "ss"". — [Python str.casefold](https://docs.python.org/3.11/library/stdtypes.html)
- **Unicode versions differ.** Python 3.11's `unicodedata` is 14.0.0 (Exp A). By contrast, unicode61 is "case-insensitive according to the rules defined by Unicode 6.1". — [FTS5 §4.3.1](https://sqlite.org/fts5.html)
- **SQLite's fold implementation.** Its table was "generated by parsing the CaseFolding.txt file", and the trigram tokenizer uses the same function. Code points ≥ 65536 are folded only in the range 66560–66600 (Deseret). — [fts5_unicode2.c](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_unicode2.c), [fts5_tokenize.c](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_tokenize.c)
- **Unicode CaseFolding.txt.** Status C+S gives simple folding and C+F gives full folding. T is the special case for Turkic dotted/dotless I and is normally excluded. Relevant lines:
  - `0049; T; 0131`, `0130; F; 0069 0307`, `0130; T; 0069`
  - `1E9E; S; 00DF`, `017F; C; 0073`, `212A; C; 006B`, `03C2; C; 03C3`
  - `1C90; C; 10D0` (Georgian Mtavruli), `AB70; C; 13A0` (Cherokee)

  — [Unicode CaseFolding.txt (UCD latest, 18.0.0 header)](https://www.unicode.org/Public/UCD/latest/ucd/CaseFolding.txt)
- **Exp A: how Python's classes map onto SQLite's fold.** Every Python IGNORECASE equivalence class was mapped through SQLite's trigram fold. Of **1,427 classes with more than one member** (2,886 code points), **402 are not unified by SQLite**.

  | Script | Split classes |
  |---|---|
  | Cherokee | 86 |
  | Old Hungarian/Old Italic etc. ("OLD") | 51 |
  | Georgian | 46 |
  | Osage | 36 |
  | Vithkuqi | 35 |
  | Adlam | 34 |
  | Latin | 32 |
  | Warang Citi | 32 |
  | Medefaidrin | 32 |
  | Cyrillic | 14 |
  | Greek | 3 |
  | Glagolitic | 1 |

  - The class {I, i, İ, ı} folds to **three** SQLite values: i, İ, ı.
  - SQLite does unify ſ→s, K (Kelvin)→k, µ→μ, ς→σ, ẞ→ß, ϑ/ϴ→θ, and Deseret.
- **Exp A: the effect on substring queries.** `MATCH '"istanbul"'` returns `istanbul` and `ISTANBUL` but **not** `İstanbul`, while `MATCH '"İSTANBUL"'` returns only `İstanbul`.
- **Exp F: `remove_diacritics` only half-helps with Turkish.** With `trigram remove_diacritics 1`, `"istanbul"` does find `İstanbul`, because İ decomposes to I plus a dot. But `"ispanak"` does **not** find `ıspanak`, because ı is a base letter.
- **Exp B: impact on the real data.** 87 labels contain İ, 955 contain ı, 52 contain Cherokee and 1 contains Adlam. The test used 150 random lower-cased 4-character windows, cut from random labels that contain I, i, İ or ı. For **5 needles**, trigram MATCH missed rows that `re.I` finds. For example, `'arı '` missed **155** rows, and `'im s'` missed 3. For the same needles, casefold found no extra rows.
- **The grepper uses three different case semantics.** — [acatalogue/grep.py](file:///home/user/acatalogue/acatalogue/grep.py), [db.py](file:///home/user/acatalogue/acatalogue/db.py)
  - Substring needles of 3 or more characters use trigram MATCH, which is SQLite's fold.
  - Needles under 3 characters use `casefold_contains`, which is Python's full casefold.
  - Hit highlighting uses `re.IGNORECASE`.
  - Regex mode prefilters only case-sensitive patterns that have a top-level literal run.
- **Normalization.** A composed (NFC) `'café'` does not match decomposed (NFD) `'Café'` on a default trigram table, but does with `remove_diacritics 1` (Exp A). The data contains **0** non-NFC labels or passages (Exp B).
- **Exp C: soundness of a Python "key" fold.**
  - Define key(c) = min({lower(c)} ∪ EXTRA[lower(c)]). This is a canonical member of c's `re.I` class, and it maps one code point to one code point.
  - **0** code points violate key(upper(lower(c))) = key(c). Expanding IGNORECASE ranges and classes member by member through key() is therefore sound.
  - The false-negative fuzz in §1 also passed on this index.
- **Exp B: sub-3-character phrases silently drop rows** inside AND and OR expressions.
- **External-content rowid stability.**
  - "The VACUUM command may change the ROWIDs of entries in any tables that do not have an explicit INTEGER PRIMARY KEY." — [SQLite VACUUM](https://sqlite.org/lang_vacuum.html)
  - "It is the responsibility of the user to ensure that an FTS5 external content table… is kept consistent with the content table". — [FTS5 §4.4.4](https://sqlite.org/fts5.html)
  - acatalogue's `label` table has a composite `PRIMARY KEY (concept_id, lang, kind, text)`, so its rowid has no alias. `label_fts` and `label_tri` use `content='label'` with the default rowid. — [schema.sql](file:///home/user/acatalogue/acatalogue/schema.sql)
  - The build runs `'rebuild'` on the FTS tables. In the package code, `VACUUM` appears only in `corpusfile.py`, which handles the sealed corpus files. `passage_*` is safe because it uses `content_rowid='id'`, an INTEGER PRIMARY KEY. `concept_fts` and `concept_tri` store their own content. — [build.py](file:///home/user/acatalogue/acatalogue/build.py), [schema.sql](file:///home/user/acatalogue/acatalogue/schema.sql)
  - Exp F: the tables are aligned today. There were 0 misses in 1,840 self-queries, and `PRAGMA integrity_check` returned `ok` in 0.5 s.

### Inferences
- **"Never miss a true match" needs a defined notion of "true".** Recommendation: define case-insensitive matching as **Python `re.IGNORECASE` literal equivalence**. It is what regex `(?i)` and the highlighter already use, and it is length-preserving (one code point to one code point), so highlight offsets stay exact.
  - Casefold ('ß'→'ss') changes string lengths and would break trigram and offset alignment.
  - Under this definition, 'arı' matching 'ari' is *correct* behaviour.
- **The cleanest guarantee is a key-folded index.** Store `key(text)` in a contentless `trigram case_sensitive 1` table, so SQLite does no folding at all, and query it with `key(needle)`.
  - For literals, MATCH on the key index is a sound superset of `re.search(re.escape(needle), text, re.I)`. Any text character that `re.I` equates with a needle character has the same key, so there are no false negatives.
  - It coincides with `re.I` except in possible edge cases. sre compares uncased pattern characters exactly, so a character whose lowercase is an uncased character could produce a false positive. Keep a cheap `re.I` verification on the candidates.
  - For regexes, it is a sound superset whether or not the regex is case-sensitive.
  - The Unicode 6.1 dependency disappears.
- **A cheaper alternative keeps the existing index.** For each needle character, OR together the SQLite-distinct folds of its `re.I` class members. FTS5 phrases cannot contain alternation, so the query becomes an AND of OR-groups of trigrams, followed by Python verification. This works because only 402 classes are split, but it is more complex and still depends on SQLite's frozen tables.
- **Version skew is the new pitfall.** If the key index is built with one Python/Unicode version and queried with another, key() can differ and cause false negatives. Store `sys.version_info` and `unicodedata.unidata_version` with the index. On mismatch, fall back to a full scan and ask for a rebuild.
  - The same applies to the private `re._casefix` and `_sre` APIs, which the grepper already relies on through `re._parser`.
- **Normalization mismatches cost recall in both engines, not prefilter soundness.** Python `re` also compares code points, so an NFD query misses NFC text in the regex as well. Since the data is 100% NFC, NFC-normalize the *query* in words and substring modes. Do not auto-normalize regex patterns, because that can change class semantics; issue a warning instead.
- **The external-content design depends on rowids that `VACUUM` may renumber.** Anyone who runs `VACUUM` on the built DB without a `rebuild` could desynchronize the FTS tables silently, which would produce both false negatives and wrong hits.

### Gaps
- Split-class characters were not counted in concept labels, scope notes or passages. Compatibility characters that NFKC would fold (fullwidth Latin, Arabic presentation forms) were not examined.
- It was not verified whether later CPython versions (3.12–3.14) change `_casefix` or the Unicode version enough to alter keys for characters present in the data.

## 4. Multilingual word search: unicode61 limits (CJK, Thai, Indic, Arabic, Turkish) and what is practical from Python's `sqlite3`

### Takeaway
With its default `categories "L* N* Co"`, unicode61 treats combining marks (Mn/Mc) as separators, so Devanagari, Tamil, Bengali, pointed Hebrew, vocalized Arabic and Thai words fall apart into fragments. On acatalogue's Devanagari labels, word-query precision is 0.171; adding `M*` raises it to 1.000. CJK runs become single tokens, so word-mode recall for 2-character CJK words is 0.370. A Lucene-style bigram shadow column raises it to 1.000.

Custom FTS5 tokenizers cannot be registered from the standard `sqlite3` module. The practical design is therefore to pre-normalize and pre-segment text in Python at build time, into shadow columns, and apply the same function to queries.

### Cited Findings
- **unicode61's classification.** "All unicode characters assigned to a general category beginning with 'L' or 'N'… or to category 'Co'… are considered tokens. All other characters are separators." The default is "L* N* Co". The documented example adds Mn with `categories 'L* N* Co Mn'`. Diacritics are removed only from Latin script characters. — [FTS5 §4.3.1 Unicode61](https://sqlite.org/fts5.html)
- **Combining diacritics can extend a token.** A character is kept inside a token if it is alphanumeric *or* `sqlite3Fts5UnicodeIsdiacritic`, which covers only a bitmask of U+0300–U+0331. Indic and Thai marks are not in that set. — [fts5_tokenize.c](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_tokenize.c), [fts5_unicode2.c](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_unicode2.c)
- **Exp A: tokens from `unicode61 remove_diacritics 2`, as acatalogue uses it today, compared with `categories 'L* N* Co M*'`.**

  | Input | Default categories | With `M*` |
  |---|---|---|
  | Hindi `हिन्दी भाषा` | `ह, न, द, भ, ष` | `हिन्दी, भाषा` |
  | Tamil `தமிழ்` | `தம, ழ` | `தமிழ்` |
  | Bengali `বাংলা` | `ব, ল` | `বাংলা` |
  | Pointed Hebrew `עִבְרִית` | `ע, ב, ר, ית` | whole word |
  | Vocalized Arabic | fragmented | whole words, **harakat kept** |
  | Thai `ภาษาไทยเป็นภาษาราชการ` | `ภาษาไทยเป, นภาษาราชการ` (split at a mark) | one unsegmented token |

  - CJK in both cases: `東京都庁の日本語` → a single token, `中华人民共和国` → a single token.
  - Korean splits on spaces.
  - Turkish `İstanbul ISPARTA ılık` → `istanbul, isparta, ılık`. İ becomes i through diacritic removal, but ı stays distinct.
- **Real-data exposure** (Exp B):

  | Label property | Count |
  |---|---|
  | contains Mn/Mc marks | 11,070 |
  | contains CJK/kana/hangul | 9,825 |
  | contains Thai | 820 |
  | shorter than 3 characters | 2,698 |
  | CJK and 2 characters or fewer | 2,337 (e.g. `音響`, `声学`) |

- **Exp D: 150 random Devanagari words, queried as phrases over the 2,899 Devanagari labels.**
  - Default categories: 1,798 rows returned, 307 correct. **Precision 0.171**, recall 1.000.
  - `M*`: 307 returned, 307 correct. **Precision 1.000**, recall 1.000.
- **Exp D: 100 random 2-character CJK words against the CJK labels.** The substring truth is 755 rows.
  - Word mode (unicode61) finds 279, a **recall of 0.370**.
  - A bigram-segmented column indexed with unicode61, queried as a phrase of bigrams, finds 755: **recall 1.000, precision 1.000**.
- **Exp D: index sizes on labels (contentless).** unicode61: 3.56 MB. With `M*`: 3.62 MB. Bigram-segmented: 5.64 MB.
- **Exp D: stray combining marks produce odd tokens under `M*`.** They give an empty token or a lone mark such as `ّ`.
- **Lucene's CJK bigram approach.** `CJKBigramFilter` "forms bigrams of CJK terms" for Han, Hiragana, Katakana and Hangul. A CJK character with no neighbour is output as a unigram, and the `outputUnigrams` option emits both. Mixed-script tokens are not bigrammed. — [Lucene CJKBigramFilter](https://lucene.apache.org/core/9_12_0/analysis/common/org/apache/lucene/analysis/cjk/CJKBigramFilter.html)
- **FTS5's built-in tokenizers** are unicode61 (Unicode 6.1, the default), ascii, porter and trigram, plus a C API for custom tokenizers. — [FTS5 §4.3](https://sqlite.org/fts5.html)
  - The ICU tokenizer exists only for FTS3/4, requires `SQLITE_ENABLE_ICU`, and takes a locale such as `tokenize=icu th_TH`. It "splits the input text according to the ICU rules for finding word boundaries". — [SQLite FTS3 docs](https://sqlite.org/fts3.html)
- **Registering a custom FTS5 tokenizer** requires the `fts5_api` pointer, obtained from `SELECT fts5(?1)` with `sqlite3_bind_pointer(…, "fts5_api_ptr", …)`. — [FTS5 §7 Extending FTS5](https://sqlite.org/fts5.html)
  - The `locale=1` option and `fts5_tokenizer_v2` (3.47.0) allow locale-aware custom tokenizers. — [changes](https://sqlite.org/changes.html)
- **Workarounds from Python.**
  - `sqlitefts` registers Python tokenizers for FTS3/4 and FTS5 via CFFI. It requires "sqlite3 has to be dynamically linked" and warns that "all connections using this modules should be explicitly closed… it can be crashed if a connection is left open". — [sqlite-fts-python](https://github.com/hideaki-t/sqlite-fts-python)
  - APSW is a separate SQLite driver. According to its changes page it added "FTS5 support including registering and calling tokenizers" and `apsw.unicode` word segmentation in 3.47.0.0. That version number was obtained through a page summary and not re-verified verbatim. The latest version is 3.53.4.0. — [APSW changes](https://rogerbinns.github.io/apsw/changes.html), [APSW text search](https://rogerbinns.github.io/apsw/textsearch.html)
- **Loading extensions from Python.** "The sqlite3 module is not built with loadable extension support by default, because some platforms (notably macOS) have SQLite libraries which are compiled without this feature". — [Python sqlite3 docs](https://docs.python.org/3.11/library/sqlite3.html). In this container `enable_load_extension` is available (Exp F).
- **Arabic is not normalized by SQLite.** `remove_diacritics` does not strip Arabic marks: a trigram `remove_diacritics 1` query for `العربية` does not find `العَرَبِيَّة` (Exp B). unicode61 with `M*` keeps harakat inside the token (Exp A).

### Inferences
- **Adopt `categories 'L* N* Co M*'`** in all three unicode61 tables (SQLite ≥ 3.25.0). It is the single highest-value word-mode fix, it is nearly free (+1.7% index size), and it applies to 11,070 labels.
  - The earlier "recall 1.0" does not mean the default is fine. It holds only because the query is fragmented the same way. Precision, highlight quality, prefix queries and NEAR are all degraded.
- **CJK and Thai need segmentation that the standard library lacks.**
  - For CJK, an overlapping-bigram shadow column is proven here: recall 0.37 → 1.0 for +2.1 MB. Emit a unigram for isolated characters, as Lucene does.
  - For Thai, bigrams would over-match more, and dictionary segmentation (ICU or APSW) needs a non-stdlib dependency. Keep Thai on the trigram substring path, and document that word mode cannot find words inside Thai runs.
- **Arabic and Hebrew need Python-side normalization after `M*`.** Normalize the indexed text and the query with the same function: strip harakat U+064B–U+065F and U+0670, remove tatweel U+0640, and optionally unify alef forms. Otherwise vocalized and unvocalized forms stop matching once marks are kept.
  - This must go into a shadow column, because unicode61 cannot do it.
  - For highlights, map character offsets back to the original text, which only works if the normalization is length-preserving.
- **Turkish is handled partly.** Word mode already maps İ→i through diacritic removal, but ı is distinct. Applying the §3 key fold before tokenizing, so that I/i/İ/ı are equal, would make word mode consistent with substring and regex. The cost is conflating distinct Turkish word pairs (e.g. *sık*/*sik*). That is acceptable for grep and debatable for ranking, so it should be optional.
- **Tokenizers written in Python are possible only through `sqlitefts` (fragile) or APSW (a different driver).** Neither fits "stdlib-only". Pre-segmented shadow columns achieve the same result with the stock unicode61 tokenizer and remain visible in the executed SQL.

### Gaps
- Arabic labels with harakat were not counted, and Arabic normalization rules were not tested on real labels.
- No source was found on whether APSW's UAX #29 segmentation handles Thai word boundaries, which usually need a dictionary; this was not tested.
- ICU and APSW were not benchmarked.

## 5. Ranking and snippets: bm25 column weights, combining scores across FTS tables, prefix indexes, highlight()/snippet() with trigram tables, detail trade-offs

### Takeaway
bm25 scores depend on each table's own statistics (row count, average document length, and IDF clamped at 1e-6), so scores from `concept_fts`, `passage_fts` and `label_fts` are not comparable. Either keep results grouped by scope or fuse them by rank, for example with RRF (k=60). On trigram tables, `highlight()` marks the exact substring even across case differences. `snippet()` counts trigram tokens, about one per character, so it is useless for context. Prefix indexes cost +58% on labels. `detail=` savings are either negligible or disable needed features.

### Cited Findings
- **bm25 in FTS5.** "The better the match, the numerically smaller the value returned". k1 = 1.2 and b = 0.75 are hard-coded. `avgdl` is "the average number of tokens in all documents within the FTS5 table". The result is multiplied by −1. Trailing arguments are per-column weights. — [FTS5 §5.1.1](https://sqlite.org/fts5.html)
- **IDF clamping.** When a term appears in more than half the rows, IDF becomes negative, so "the minimum allowable IDF is (1e-6)": `if( idf<=0.0 ) idf = 1e-6;`. — [fts5_aux.c](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_aux.c)
- **Sorting by rank.** "Using 'rank' is faster than using bm25()" when sorting, especially with LIMIT. The rank function can be set per query with `rank MATCH 'auxiliary-function-name(arg1, arg2, ...)'`. — [FTS5 §5.2](https://sqlite.org/fts5.html)
- **acatalogue's current ranking.** — [grep.py](file:///home/user/acatalogue/acatalogue/grep.py)
  - Concepts are ranked with `bm25(concept_fts, 0.0, 10.0, 5.0, 1.0)`, the weights for id, label, alts and scope_note.
  - Passages and labels use the default bm25.
  - Each scope runs with its own `LIMIT`, and hits are appended in the order concepts, passages, labels. There is no cross-scope ranking.
- **Reciprocal rank fusion.** `score += 1.0 / (k + rank(result(q), d))` with a default `rank_constant` of 60. "RRF requires no tuning, and the different relevance indicators do not have to be related to each other". — [Elasticsearch RRF docs](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion). Original paper: Cormack, Clarke & Büttcher, SIGIR 2009 — [PDF](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
- **highlight().** "In cases where two or more phrase instances overlap… a single open and close marker is inserted". — [FTS5 §5.1.2](https://sqlite.org/fts5.html)
  - Exp A: on a trigram table, `highlight(tri,0,'[',']')` for `"stanb"` gives `İ[stanb]ul`, `i[stanb]ul` and `I[STANB]UL`. For `"cdefg" AND "pqr"` it gives `ab[cdefg]hij KLMNO[PQR]ST`.
- **snippet().** Its token limit "must be greater than zero and equal to or less than 64". — [FTS5 §5.1.3](https://sqlite.org/fts5.html)
  - Exp A: on a trigram table, `snippet(…, 8)` returned `…j [KLMNO]PQR…`, which is about 10 characters.
- **Contentless tables.** "Attempting to read any column value except the rowid from a contentless FTS5 table returns an SQL NULL value", so `highlight()` and `snippet()` cannot run on them. — [FTS5 §4.4.1](https://sqlite.org/fts5.html)
- **Prefix indexes.** They record "all instances of prefix tokens of a certain length" to speed up `abc*` queries, which otherwise need a range scan. They are enabled with `prefix='2 3'`. — [FTS5 §4.2](https://sqlite.org/fts5.html)
  - Exp D: on labels, `prefix='2 3'` grows the contentless unicode61 index from 3.56 MB to **5.64 MB (+58%)**.
- **`detail=` restrictions.** `detail=column` disables phrase and NEAR queries, and `detail=none` also disables column filters. — [FTS5 §4.6](https://sqlite.org/fts5.html)
  - Exp D: trigram on labels is 13.31 MB with `full`, 13.22 MB with `column` and 9.39 MB with `none`.

### Inferences
- **Do not compare bm25 across tables.** The current grouped output is honest. If a single ranked list is wanted, fuse per-scope ranks with RRF (k=60) rather than raw scores, and show the per-scope rank in the output for transparency.
  - Rank ties from substring and regex modes (all `score=1.0`) need a deterministic tie-break, such as the current length order.
- **Use `ORDER BY rank` with `rank MATCH 'bm25(0.0,10.0,5.0,1.0)'`** instead of aliasing a `bm25()` expression as `rank`. It is documented as faster with LIMIT, although at this data size the gain is probably small (not measured).
- **Keep Python-computed spans for highlighting in substring and regex modes.** They make highlights follow exactly the same semantics as the filter, which is required once the key fold is adopted, and they work with contentless tables. Use FTS5 `highlight()`/`snippet()` only on unicode61 tables, where `M*` makes the highlighted units whole words.
- **Keep `detail=full`** on unicode61 tables, because phrases and NEAR are exposed features. On trigram tables, `detail=full` is needed for exact multi-character phrases. `columnsize=0` is the only size change that loses nothing on trigram tables.
- **Add prefix indexes only after measuring slow `word*` queries.** At 121k short labels, prefix range scans are likely already fast; this was not measured.

### Gaps
- `prefix*` query latency with and without prefix indexes was not measured, and the ranking changes were not evaluated with relevance judgments.
- The RRF paper's PDF could not be text-extracted here, so its exact wording (including why k=60 was chosen) is cited through the Elastic documentation.

## 6. Existing SQLite regexp extensions (sqlean regexp, sqlite-regex, SQLite's own regexp.c): do they help?

### Takeaway
They can only speed up the *verification scan*, by moving it from a Python callback into C or Rust. None of them adds index acceleration, and FTS5 never consumes REGEXP constraints. Each implements a *different regex dialect and different case-folding rules* from Python `re`: PCRE2, the Rust `regex` crate (no lookaround or backreferences), and POSIX ERE with an ASCII-only `\w`. Using one for filtering while Python highlights would recreate the semantic mismatch described in §3. At acatalogue's scale, where a full Python REGEXP scan takes 12–93 ms, they are optional at most.

### Cited Findings
- **sqlean `regexp`.** It is "Based on the PCRE2 engine" and provides the `REGEXP` operator plus `regexp_like`, `regexp_substr`, `regexp_capture` and `regexp_replace`. It "supports Unicode in character classes (like `\w`) and assertions (like `\b`)", and case-insensitivity uses `(?i)`. — [sqlean regexp docs](https://github.com/nalgeon/sqlean/blob/main/docs/regexp.md)
- **sqlite-regex.** It is built on Rust's regex crate. It provides `regexp`, `regex_find`, `regex_find_all`, `regex_captures`, `regex_replace(_all)`, `regex_split` and `regexset`, and installs with `pip install sqlite-regex` for loading as an extension. — [asg017/sqlite-regex](https://github.com/asg017/sqlite-regex)
  - The Rust crate "lacks several features… look-around and backreferences", and in exchange guarantees worst-case O(m·n) time. — [docs.rs regex](https://docs.rs/regex/latest/regex/)
- **SQLite's `ext/misc/regexp.c`** supports a POSIX ERE subset, with `\w` defined as "[A-Za-z0-9_]". It is compiled into the CLI (since 3.36.0), not into the library that Python loads. — [regexp.c](https://github.com/sqlite/sqlite/blob/master/ext/misc/regexp.c), [changes](https://sqlite.org/changes.html)
- **FTS5 never uses REGEXP constraints.** Its `xBestIndex` handles only MATCH, LIKE/GLOB and rowid. — [fts5_main.c](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_main.c)
- **Timing of Python REGEXP scans** (Exp B):

  | Query | Time |
  |---|---|
  | Full scan of 121,717 labels, case-sensitive | 68.5 ms |
  | Full scan of labels, `(?i)` | 92.7 ms |
  | Full scan of 1,935 passages | 12.4 ms |
  | Trigram-prefiltered query | 0.1 ms |
  | `casefold_contains` scan of labels | 66.8 ms |

- **Loading extensions is not guaranteed.** Python's `sqlite3` is not built with loadable-extension support by default. — [Python sqlite3 docs](https://docs.python.org/3.11/library/sqlite3.html)

### Inferences
- **A prefilter saves far more than a faster engine would.** A Cox-style prefilter cuts latency by 2–3 orders of magnitude. A faster engine could at best speed up the Python-callback scan by a constant factor, which was not measured.
- **Dialect drift is a correctness problem.** Examples:
  - Rust rejects lookaround and backreferences.
  - PCRE2's Unicode case rules differ from sre's `_casefix`.
  - `regexp.c`'s `\w` is ASCII-only.
- **If an extension is ever used, it must stay optional and be used for both filtering and highlighting,** with the dialect shown in the UI. Python `re` remains the default semantics.

### Gaps
- sqlean and sqlite-regex were not benchmarked against Python REGEXP on this data, and their Unicode case-folding tables were not checked against Python's.

## 7. Prioritized recommendations for acatalogue's grepper (each with evidence, SQLite and Python requirements, and pitfalls)

### Takeaway
Fix correctness and consistency first:

1. One case-insensitive semantics, enforced by a Python key-folded trigram index.
2. `M*` tokenization for word tables.
3. Rowid stability for the external-content FTS tables.

Then add performance and recall:

4. A Cox-style regex prefilter on the key index.
5. CJK bigram shadow columns.
6. NFC-normalized queries.

Everything works from Python 3.11's standard `sqlite3` module on SQLite 3.45. No extension is required.

### Cited Findings
- Case-folding mismatch: 402 split classes; `İstanbul` missed; 155 rows missed for one real needle; three different case semantics inside the grepper. — §3, Exp A/B, [grep.py](file:///home/user/acatalogue/acatalogue/grep.py)
- Key fold soundness: 0 closure violations; key-folded contentless trigram index of labels 9.02 MB, built in about 3 s. — §3, Exp C/D
- Cox prototype: 0 false negatives over 400 patterns; 348 vs 209 of 400 prefilterable; median 2 candidates; 11.53 s → 0.10 s. — §1, Exp C
- Tokenization: Devanagari precision 0.171 → 1.000 with `M*`; CJK 2-character recall 0.370 → 1.000 with bigrams (+2.08 MB). — §4, Exp D
- Sub-3-character phrases in AND/OR drop rows; EXPLAIN QUERY PLAN shows `L0` even when FTS5 scans. — §2, Exp A/B
- VACUUM can renumber rowids of tables without an INTEGER PRIMARY KEY; the `label` table has a composite PK with external-content FTS on the default rowid. — [SQLite VACUUM](https://sqlite.org/lang_vacuum.html), [schema.sql](file:///home/user/acatalogue/acatalogue/schema.sql)
- bm25 statistics are per table; RRF needs no score calibration. — §5

### Inferences

#### P0.1 Define case-insensitivity once, as Python `re.IGNORECASE` literal equivalence, and enforce it with a key-folded trigram index
**Change.**
- Add `key(s)`, the per-code-point `re.I` class representative computed as in Exp C from `_sre.unicode_tolower` and `re._casefix._EXTRA_CASES`.
- Register it with `conn.create_function('rekey', 1, key, deterministic=True)`.
- Replace or add trigram tables so that the step is visible as SQL in `acat build`:
  ```sql
  CREATE VIRTUAL TABLE label_key USING fts5(k, tokenize='trigram case_sensitive 1', content='', columnsize=0);
  INSERT INTO label_key(rowid, k) SELECT rowid, rekey(text) FROM label;
  ```
- Do the same for concepts and passages.
- Substring mode for needles of 3 or more characters then uses `label_key MATCH '"'||rekey(needle)||'"'`, with embedded `"` doubled. For literals this is a sound superset of `re.search(re.escape(needle), text, re.I)`; verify the candidates with `re.I` (§3).
- The under-3-character path must use the same semantics (`rekey(needle) in rekey(text)`) instead of `casefold`.
- Highlights keep using `re.I`, so the filter and the highlighter agree by construction.

**Requirements.** SQLite ≥ 3.34.0 (trigram `case_sensitive`) and Python 3.11+ (`re._casefix`).

**Pitfalls.**
- **Version skew.** Store the Python version and `unicodedata.unidata_version` in a meta row. On mismatch, full-scan and flag a rebuild.
- **Private APIs.** Add a unit test that asserts `re.fullmatch(re.escape(chr(a)), chr(b), re.I)` if and only if key(a) == key(b) over all class members, plus the closure property from Exp C.
- **Contentless tables** cannot use `'rebuild'` or `highlight()`, so they must be populated explicitly.
- **Behaviour change to document.** `arı` now matches `ARI`. This is intended under `re.I` semantics.

#### P0.2 Tokenize words with `unicode61 remove_diacritics 2 categories 'L* N* Co M*'`
**Change.** Apply it to `concept_fts`, `label_fts` and `passage_fts`, then rebuild.

**Evidence.** Precision rises from 0.171 to 1.000 for Devanagari words, the change affects 11,070 labels, and the index grows by only 1.7%. It needs SQLite ≥ 3.25.0.

**Pitfalls.**
- Arabic and Hebrew marks now stay inside tokens, so vocalized and unvocalized forms stop matching. Pair this with the normalization in P1.6.
- Stray marks produce empty or lone-mark tokens, which is harmless.
- Existing query behaviour changes for these scripts; add regression tests.

#### P0.3 Make the external-content FTS tables robust to rowid changes
**Change.** Give `label` an `INTEGER PRIMARY KEY` and point the FTS tables at it with `content_rowid`, or never VACUUM without `'rebuild'`. Add `PRAGMA integrity_check`, which covers FTS5 since 3.44.0 and works read-only since 3.45.1, to `acat verify`.

**Evidence.** The VACUUM rowid rule applies because of the composite PK; the tables are aligned today. The same concern applies to any rowid-keyed key table created under P0.1.

#### P1.4 Replace `required_literal` with a Cox/codesearch extractor over `re._parser`, targeting the key index
**Change.** Implement the extractor:
- Merge runs of consecutive literals first.
- Map each literal through key(), so `(?i)` needs no case-variant explosion.
- Handle small classes (≤ 30 members, via key) and bounded repeats.
- Treat lookarounds and anchors as zero-width, and backreferences, conditionals, `*` and large classes as ANY.
- Apply the caps maxExact 7 and maxSet 20, and cap the output at, for example, 64 phrases with depth ≤ 20 (FTS5's limit is 256).

Emit AND/OR of double-quoted phrases with `"` doubled, and always verify with `REGEXP`. Record the generated MATCH string in `res.sql` and `res.notes` for transparency.

**Evidence.** 0 false negatives over 400 patterns; 348 vs 209 of 400 prefilterable; median 2 candidates. A label full scan takes about 70–90 ms, against about 0.1 ms prefiltered; a passage full scan takes about 12 ms. The gain matters most for `scope=all` and the API.

**Pitfalls (hard rules).**
- Never emit a string shorter than 3 characters.
- An OR with any ANY branch becomes ANY.
- When a cap is hit, drop AND terms or replace the whole OR with ANY; never drop a single OR branch.
- Report "index used" from the grepper's own decision, not from EXPLAIN QUERY PLAN.
- Keep a property-based test that compares prefiltered results with a full scan on the built DB.

#### P1.5 Add a CJK bigram shadow column (Lucene CJKBigramFilter approach)
**Change.**
- At build time, rewrite Han, kana and Hangul runs as space-separated overlapping bigrams (a unigram for isolated characters), leaving other text as is.
- Index the result with unicode61 in a contentless table.
- In word mode, turn CJK query runs into phrases of bigrams.
- In substring mode, use the same table to prefilter 2-character CJK needles (2,337 labels are 2 characters or fewer) instead of full-scanning, with Python verification.

**Evidence.** Recall rises from 0.370 to 1.000 at precision 1.000, for +2.08 MB on labels.

**Pitfalls.**
- Bigrams span word boundaries, which is acceptable for grep but gives weaker bm25 semantics.
- A single-character query needs unigrams, via `outputUnigrams`, or a scan.
- Thai is not covered.

#### P1.6 Normalize the query side
**Change.** NFC-normalize the needle and word queries; the data is 100% NFC. Do not auto-normalize regexes; warn if a pattern is not NFC. Optionally add an Arabic/Hebrew normalized shadow column (strip U+064B–U+065F, U+0670, U+0640) with the same function applied to queries.

#### P2.7 Rank honestly across scopes
**Change.** Keep grouped output by default. Offer an RRF-fused view (k=60) instead of mixing raw bm25 values. Switch to `ORDER BY rank` with `rank MATCH 'bm25(…)'`.

**Evidence.** bm25's per-table avgdl and IDF, the clamp at 1e-6, the Elastic RRF documentation, and "rank is faster" all support this.

#### P2.8 Keep snippets consistent with the filter
**Change.** For trigram-backed modes, keep Python span windows: `snippet()` on trigram tables yields about 8–10 characters, and contentless tables cannot highlight at all. For word mode, `highlight()` becomes word-level once `M*` is in place. If shadow columns are highlighted, map character offsets back to the original text, which requires length-preserving normalization.

#### P3.9 Optional extras
- **Accent-insensitive substring mode.** Add a second trigram table with `remove_diacritics 1`, which needs SQLite ≥ 3.45.0.
  - It works with MATCH only; LIKE/GLOB are not indexed.
  - Removal is Latin-only: Greek tonos and Arabic harakat are untouched.
  - It maps İ to i but not ı. Verify results with a Python accent-stripping function that matches this behaviour.
- **Extensions and alternative drivers.** sqlean `regexp`, sqlite-regex and APSW (UAX #29 tokenizers) are acceptable only behind a feature flag, because their semantics differ from Python `re` (§6).
- **Size.** `columnsize=0` on all trigram tables saves about 1.9 MB for labels. `detail=none` and `prefix=` are not recommended without a measured need.

### Gaps
- Nothing was implemented in the repository. The prototype lives in the session scratchpad (`exp3.py`) and needs productionizing and tests.
- Thai word segmentation without a non-stdlib dependency remains unsolved.
- The effect of `M*` on concept scope notes and passages, which are mostly English (only 4 passages contain marks), was not measured. It is presumably neutral.
- None of the changes was tested under concurrent API load.
