# Local, multilingual semantic and hybrid search for a SQLite catalogue (acatalogue)

*Researched 2026-09-25. Baseline being improved: LSA (TF-IDF + truncated SVD, 48 dims) over ~600 English concept texts, where "every vector is stored under that model id so a different method can be added side by side, never silently swapped" ([acatalogue/acatalogue/semantic.py](/home/user/acatalogue/acatalogue/semantic.py)). Where a number was measured by the researcher rather than taken from a publication, it says so. Where extraction from a source was unreliable, it says so.*

## 1. Multilingual embedding models for local CPU use (as of September 2026)

### Takeaway
No single model leads on every measure. The best published multilingual retrieval at ≤0.6B parameters comes from Qwen3-Embedding-0.6B (MMTEB Retrieval 64.64), IBM Granite-Embedding-311M-Multilingual-R2 (IBM reports 65.2 on 18 multilingual retrieval tasks) and EmbeddingGemma-300m (62.49). The best published cross-lingual alignment (MMTEB bitext mining) comes from multilingual-e5-large-instruct (80.13), bge-m3 (79.11) and LaBSE (76.35). Static models (potion-multilingual-128M, static-similarity-mrl-multilingual-v1) are 100–500x faster and need no torch or ONNX runtime, but they are much weaker, especially across languages (bitext mining 40.72 and 50.62). The CC BY-NC 4.0 licence rules out jina-embeddings-v3 and v5 for an open dataset project. The Gemma licence and gating make EmbeddingGemma a risk.

### Cited Findings

**Benchmark context**
- MMTEB (Enevoldsen et al., ICLR 2025) covers "over 500 quality-controlled evaluation tasks across 250+ languages". Its abstract says "the best-performing publicly available model is multilingual-e5-large-instruct with only 560 million parameters" — [MMTEB, arXiv 2502.13595](https://arxiv.org/abs/2502.13595)
- The MTEB(Multilingual) benchmark in that paper has 132 tasks. The paper says multilingual-e5-large-instruct does especially well on mid-to-low-resource languages (<300M speakers), where it beats much larger Mistral-based models — [MMTEB HTML](https://arxiv.org/html/2502.13595)
- Compared-model scores in the Qwen3 model card were "retrieved from MTEB online leaderboard on May 24th, 2025" — [Qwen3-Embedding-0.6B card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- As of July 2026, the top of the multilingual MMTEB board is Tencent KaLM-Embedding-Gemma3-12B (72.32), a 12B model. This comes from a secondary aggregator and was not checked against the leaderboard — [presenc.ai](https://presenc.ai/research/best-open-weight-embedding-models-2026)

**Model facts.** Params, dims, context and licence come from the model cards. The dates are the public release where one is stated, otherwise the Hugging Face repo creation date from `https://huggingface.co/api/models/<id>`.

| Model | Release | Params | Dims (MRL) | Max tokens | Languages | Licence | Source |
|---|---|---|---|---|---|---|---|
| BAAI/bge-m3 | repo 2024-01-27; paper Feb 2024 | ~568M | 1024 dense + sparse + multi-vector | 8192 | 100+ working languages (194 in training data) | MIT | [card](https://huggingface.co/BAAI/bge-m3), [paper](https://arxiv.org/abs/2402.03216), [HF API](https://huggingface.co/api/models/BAAI/bge-m3) |
| intfloat/multilingual-e5-small | repo 2023-06-30; report 2024-02-08 | 117.7M | 384 | 512 | 93 language tags | MIT | [card](https://huggingface.co/intfloat/multilingual-e5-small), [report](https://arxiv.org/abs/2402.05672) |
| intfloat/multilingual-e5-base | repo 2023-05-19 | 278M | 768 | 512 | 93 tags | MIT | [HF](https://huggingface.co/intfloat/multilingual-e5-base) |
| intfloat/multilingual-e5-large | repo 2023-06-30 | 559.9M | 1024 | 512 | 93 tags | MIT | [HF](https://huggingface.co/intfloat/multilingual-e5-large) |
| intfloat/multilingual-e5-large-instruct | repo 2024-02-08 | 559.9M | 1024 | 512 | 93 tags | MIT | [HF](https://huggingface.co/intfloat/multilingual-e5-large-instruct) |
| sentence-transformers/LaBSE | HF port dated 2022-03-02 | 470.9M | 768 | — | 109 | Apache-2.0 | [card](https://huggingface.co/sentence-transformers/LaBSE) |
| paraphrase-multilingual-MiniLM-L12-v2 | HF 2022-03-02 | 117.7M | 384 | 128 | 50+ | Apache-2.0 | [card](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2), [sbert](https://www.sbert.net/docs/sentence_transformer/pretrained_models.html) |
| paraphrase-multilingual-mpnet-base-v2 | HF 2022-03-02 | 278M | 768 | — | 50+ | Apache-2.0 | [HF](https://huggingface.co/sentence-transformers/paraphrase-multilingual-mpnet-base-v2) |
| Alibaba-NLP/gte-multilingual-base | repo 2024-07-20; paper 2024-07-29 | 305.4M | 768 (elastic 128–768) + sparse | 8192 | 70+ | Apache-2.0 (custom code) | [card](https://huggingface.co/Alibaba-NLP/gte-multilingual-base), [mGTE](https://arxiv.org/abs/2407.19669) |
| jinaai/jina-embeddings-v3 | paper 2024-09-16 | 572M | 1024 (to 32) | 8192 | 93 tags | **CC BY-NC 4.0** | [paper](https://arxiv.org/abs/2409.10173), [HF](https://huggingface.co/jinaai/jina-embeddings-v3) |
| jina-embeddings-v5-text-small / -nano | 2026-02-18 | 677M / 239M | 1024 / 768 (to 32) | 32768 / 8192 | 119+ | **CC BY-NC 4.0** | [small](https://huggingface.co/jinaai/jina-embeddings-v5-text-small), [nano](https://huggingface.co/jinaai/jina-embeddings-v5-text-nano) |
| Snowflake arctic-embed-m-v2.0 / l-v2.0 | repo 2024-11-08; paper Dec 2024 | 305M (113M non-emb) / 568M (303M non-emb) | 768 / 1024 (MRL 256) | 512 in fine-tuning | 74 tags | Apache-2.0 | [paper](https://arxiv.org/html/2412.04506), [card](https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0) |
| Qwen/Qwen3-Embedding-0.6B | repo 2025-06-03 (card: "as of June 5, 2025") | 595.8M, 28 layers | up to 1024 (32–1024) | 32K | 100+ | Apache-2.0 | [card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) |
| google/embeddinggemma-300m | 2025-09-04 | 308M (~100M model + ~200M embedding params) | 768 (512/256/128) | 2K | 100+ | **Gemma terms, gated** | [blog](https://developers.googleblog.com/en/introducing-embeddinggemma/), [model card](https://ai.google.dev/gemma/docs/embeddinggemma/model_card), [HF API](https://huggingface.co/api/models/google/embeddinggemma-300m) |
| ibm-granite/granite-embedding-311m-multilingual-r2 | 2026-04-29 | 311M (ModernBERT) | 768 (512/384/256/128) | 32,768 | 200+ (52 "enhanced", including tr and zh) | Apache-2.0 | [card](https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2) |
| ibm-granite/granite-embedding-97m-multilingual-r2 | 2026-04-29 | 97M (pruned 22→12 layers) | 384 | 32,768 | 200+ (52 enhanced) | Apache-2.0 | [card](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2) |
| minishlab/potion-multilingual-128M (static) | repo 2025-05-22 | 128.1M (lookup table) | 256 | unlimited (static) | 101 | MIT | [card](https://huggingface.co/minishlab/potion-multilingual-128M), [HF API](https://huggingface.co/api/models/minishlab/potion-multilingual-128M) |
| sentence-transformers/static-similarity-mrl-multilingual-v1 (static) | repo 2024-10-25; blog 2025-01-15 | lookup table | 1024 (to 32) | "inf" | ~50 tags | Apache-2.0 | [card](https://huggingface.co/sentence-transformers/static-similarity-mrl-multilingual-v1), [blog](https://huggingface.co/blog/static-embeddings) |

**MMTEB (Multilingual) scores.** All scores are on the same benchmark unless noted.

| Model | Mean(Task) | Retrieval | Bitext mining (cross-lingual) | Source |
|---|---|---|---|---|
| Qwen3-Embedding-0.6B | 64.33 | 64.64 | 72.22 | [Qwen3 card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) |
| multilingual-e5-large-instruct | 63.22 | 57.12 | 80.13 | [Qwen3 card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) |
| EmbeddingGemma-300m (768d) | 61.15 | 62.49 | 64.40 | [EmbeddingGemma paper](https://arxiv.org/html/2509.20354) |
| bge-m3 | 59.56 | 54.60 | 79.11 | [Qwen3 card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) |
| multilingual-e5-large | 58.6 | n/a | 71.7 | [MMTEB Table 2](https://arxiv.org/html/2502.13595) |
| jina-embeddings-v3 | 58.37 | 55.76 | 65.25 | [EmbeddingGemma paper](https://arxiv.org/html/2509.20354) |
| gte-multilingual-base | 58.24 | 56.50 | 71.79 | [EmbeddingGemma paper](https://arxiv.org/html/2509.20354) |
| multilingual-e5-base | 57.0 | n/a | 69.4 | [MMTEB Table 2](https://arxiv.org/html/2502.13595) |
| multilingual-e5-small | 55.5 | n/a | 67.5 | [MMTEB Table 2](https://arxiv.org/html/2502.13595) |
| LaBSE | 52.07 | 33.17 | 76.35 | [potion card](https://huggingface.co/minishlab/potion-multilingual-128M) |
| paraphrase-multilingual-MiniLM-L12-v2 | 48.8 | n/a | 44.6 | [MMTEB Table 2](https://arxiv.org/html/2502.13595) (see caveat) |
| potion-multilingual-128M | 47.31 | 37.86 | 40.72 | [potion card](https://huggingface.co/minishlab/potion-multilingual-128M) |
| static-similarity-mrl-multilingual-v1 | 47.24 | 41.21 | 50.62 | [potion card](https://huggingface.co/minishlab/potion-multilingual-128M) |
| jina-embeddings-v5-text-small / nano | 67.7 / 65.5 | — | — | [small](https://huggingface.co/jinaai/jina-embeddings-v5-text-small), [nano](https://huggingface.co/jinaai/jina-embeddings-v5-text-nano) |
| granite-311m-r2 / granite-97m-r2 | — | 65.2 / 60.3 (IBM's "MTEB ML Retrieval (18)") | — | [311m](https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2), [97m](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2) |

- **Extraction caveat.** In my extraction of MMTEB Table 2, the "Retrieval" and "STS" columns were mislabelled: they reproduce the leaderboard's STS and pair-classification values for multilingual-e5-large-instruct. Only Mean and Bitext values from that table are used above. Both match other sources for mE5-large-instruct (63.2/80.1) and LaBSE (52.1/76.4) — [MMTEB HTML](https://arxiv.org/html/2502.13595), [Qwen3 card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), [potion card](https://huggingface.co/minishlab/potion-multilingual-128M)
- **Cross-source conflict.** The EmbeddingGemma paper's table gives "Granite Multilingual 278M" a Retrieval score of 59.9 — [EmbeddingGemma paper](https://arxiv.org/html/2509.20354). IBM gives granite-embedding-278m-multilingual 52.2 on its 18-task retrieval average — [granite-311m-r2 card](https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2). The two retrieval aggregates are therefore probably not the same, so IBM's R2 figures (65.2 and 60.3) should not be ranked directly against the Qwen3/EmbeddingGemma column. EmbeddingGemma's table itself lists Qwen3-0.6B at 64.34, 64.65 and 72.23, which differ from the Qwen card only by rounding — [EmbeddingGemma paper](https://arxiv.org/html/2509.20354)

**Per-model notes**
- **bge-m3.** One model produces dense, sparse (lexical weight) and multi-vector (ColBERT) outputs. The card recommends "hybrid retrieval + re-ranking". Queries need no instruction — [bge-m3 card](https://huggingface.co/BAAI/bge-m3)
  - MIRACL dev nDCG@10 (updated July 2024 results): dense 69.2, sparse 53.9, multi-vector 70.5, dense+sparse 70.4, all three 71.5. On the same table BM25 scores 31.9 and mE5-large 66.6 — [bge-m3 paper](https://arxiv.org/html/2402.03216)
  - MKQA cross-lingual retrieval, Recall@100: dense 75.1, sparse 45.3, all 75.5, BM25 39.9, mE5-large 70.9 — [bge-m3 paper](https://arxiv.org/html/2402.03216)
  - The card notes that earlier MIRACL numbers were too low because of an evaluation bug fixed on 2024-07-01 — [bge-m3 card](https://huggingface.co/BAAI/bge-m3)
- **multilingual-e5 family.** Every input must start with "query: " or "passage: ", otherwise performance degrades. Texts are truncated at 512 tokens. The small model has 12 layers and 384 dimensions — [mE5-small card](https://huggingface.co/intfloat/multilingual-e5-small)
  - MIRACL (16 languages) nDCG@10: small 60.8, base 62.3, large 66.5, large-instruct 65.7; BM25 39.3, mDPR 41.5 — [mE5 report](https://arxiv.org/html/2402.05672)
  - Tatoeba bitext (112 languages): small 64.2, base 68.1, large 75.7, large-instruct 83.8 — [mE5 report](https://arxiv.org/html/2402.05672)
  - The instruct model is trained with instruction templates ("150k unique instructions covering 93 languages") — [mE5 report](https://arxiv.org/html/2402.05672)
- **LaBSE.** Maps 109 languages into one shared space — [LaBSE card](https://huggingface.co/sentence-transformers/LaBSE). sbert.net recommends it for bitext mining but says it "works less well for assessing the similarity of sentence pairs that are not translations of each other" — [sbert.net](https://www.sbert.net/docs/sentence_transformer/pretrained_models.html)
- **paraphrase-multilingual-*.** Trained on parallel data for 50+ languages — [sbert.net](https://www.sbert.net/docs/sentence_transformer/pretrained_models.html). The MiniLM model's maximum sequence length is 128 tokens — [card](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
- **gte-multilingual-base.** Produces sparse vectors as well as dense ones, supports 70+ languages, and has an 8192-token context — [card](https://huggingface.co/Alibaba-NLP/gte-multilingual-base). The mGTE paper says it matches "large-sized state-of-the-art BGE-M3" while being base-sized — [mGTE](https://arxiv.org/abs/2407.19669)
- **jina v3 / v5.** v3 uses task LoRA adapters and has 570M parameters — [jina v3 paper](https://arxiv.org/abs/2409.10173). v5-text-small is built on Qwen3-0.6B-Base, distilled from Qwen3-Embedding-4B, and needs `transformers>=4.57`, `torch>=2.8` and `peft` — [v5 small](https://huggingface.co/jinaai/jina-embeddings-v5-text-small), [v5 nano](https://huggingface.co/jinaai/jina-embeddings-v5-text-nano). All are **CC BY-NC 4.0** — [HF API](https://huggingface.co/api/models/jinaai/jina-embeddings-v5-text-small)
- **Arctic Embed 2.0.** nDCG@10 for M / L / bge-m3 / mE5-large:

  | Benchmark | M | L | bge-m3 | mE5-large |
  |---|---|---|---|---|
  | MTEB Retrieval | 0.554 | 0.556 | 0.488 | 0.514 |
  | CLEF | 0.534 | 0.541 | 0.410 | 0.431 |
  | MIRACL | 0.592 | 0.649 | 0.678 | 0.651 |

  Source: [Arctic 2.0 paper](https://arxiv.org/html/2412.04506). The model card's MIRACL column is a 4-language subset ("MIRACL (4)") — [card](https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0)
  - At 256 dims (MRL), the M and L models keep 99% and 98% of their MTEB-R scores — [paper](https://arxiv.org/html/2412.04506)
  - MRL combined with int4 gives "128 bytes/vector"; queries use the prefix `query: ` — [card](https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0)
- **Qwen3-Embedding-0.6B.** A decoder model (AutoModelForCausalLM, last-token pooling) that is instruction-aware. The card says that "not using an instruct on the query side can lead to a drop in retrieval performance by approximately 1% to 5%", and that transformers≥4.51 is needed — [card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), [HF](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- **EmbeddingGemma.**
  - MMTEB mean(task) by dimension: 61.15 (768d), 60.71 (512d), 59.68 (256d), 58.23 (128d); Q8_0 scores 60.93. Prompts: `task: search result | query: {content}` and `title: {title | "none"} | text: {content}` — [Google model card](https://ai.google.dev/gemma/docs/embeddinggemma/model_card)
  - With quantization it uses "sub-200MB" RAM, and it takes "<15ms … (256 input tokens) on EdgeTPU" — [Google blog](https://developers.googleblog.com/en/introducing-embeddinggemma/)
  - int4 per-block quantization gives 60.62 and int8 gives 60.93 — [paper](https://arxiv.org/html/2509.20354)
  - Licence: the HF metadata says `license: gemma`, `gated: manual` — [HF API](https://huggingface.co/api/models/google/embeddinggemma-300m). Google's docs page also links a "Gemma 4 license" (Apache-2.0) page, but that seems to cover the Gemma 4 family, not this Gemma-3-based model (unresolved; see Gaps) — [model card](https://ai.google.dev/gemma/docs/embeddinggemma/model_card)
- **Granite R2.**
  - Architecture: ModernBERT, with a 262K-token vocabulary in the 311m model and 180K in the 97m. The 311m model's MRL results on ML retrieval: 63.9 (768d), 63.9 (512d), 63.8 (384d), 63.5 (256d). Training data uses "permissive, enterprise-friendly licenses". It ships ONNX and OpenVINO files and can be converted to GGUF; "Ollama does not currently support ModernBERT-based models". IBM says mE5-small scores 50.9 on its 18-task retrieval average — [311m card](https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2), [97m card](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2)
  - The MRL table's 768d value (63.9) does not match the headline 65.2 in the same card — [311m card](https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2)
- **potion-multilingual-128M.** Built with Tokenlearn: a Model2Vec distillation of bge-m3 over 2M C4 sentences in 101 languages. The card says it is the "most performant static multilingual model, reaching 90.86% of the performance of LaBSE" (mean 47.31 vs 52.07) — [card](https://huggingface.co/minishlab/potion-multilingual-128M). The weights are a 512 MB float32 safetensors file plus an 18.6 MB tokenizer.json — [file listing](https://huggingface.co/minishlab/potion-multilingual-128M/tree/main)
- **static-similarity-mrl-multilingual-v1.**
  - The card says it is "100x to 400x faster" than multilingual-e5-small on CPU (i7-13700K), and 10–25x faster on GPU. Both the card and the blog state it is "not intended for retrieval use cases" — [card](https://huggingface.co/sentence-transformers/static-similarity-mrl-multilingual-v1)
  - The blog gives it ~125x mE5-small's CPU speed, and 92.3% of mE5-small's STS score. It uses the bert-base-multilingual-uncased tokenizer — [blog](https://huggingface.co/blog/static-embeddings)

**What runs without torch (and what "numpy-only" really means)**
- Model2Vec's core runtime dependencies are `jinja2, joblib, numpy, safetensors, tokenizers>=0.20, tqdm, huggingface-hub>=1.0.0`. torch appears only in the `distill`, `train` and `onnx` extras. Python ≥3.10 is required — [pyproject](https://github.com/MinishLab/model2vec/blob/main/pyproject.toml). Version 0.9.0 (2026-08-12) is a 0.06 MB pure-Python wheel — [PyPI](https://pypi.org/pypi/model2vec/json)
- The README says "the base package's only major dependency is numpy" and claims models up to "500 times faster" and 50x smaller — [model2vec README](https://github.com/MinishLab/model2vec)
- Sentence-Transformers' `StaticEmbedding` gives "50x-500x speedups at ~10-20% performance cost" — [ST v3.2.0 notes](https://github.com/UKPLab/sentence-transformers/releases/tag/v3.2.0). Sentence-Transformers 6.1.0 itself requires `torch>=2.2`, and the torch 2.14.0 macOS arm64 wheel is 127.3 MB — [PyPI ST](https://pypi.org/pypi/sentence-transformers/json), [PyPI torch](https://pypi.org/pypi/torch/json)

### Inferences
- **No transformer runs on numpy alone.** Only static-embedding models run without a neural runtime, and even they need the Rust `tokenizers` wheel (3.1 MB on macOS arm64 per [PyPI](https://pypi.org/pypi/tokenizers/json)) and `safetensors`. Every transformer model in the list needs ONNX Runtime, llama.cpp or torch (see §2).
- **What acatalogue's queries look like.** Most queries are short concept names in some language, which makes the task closer to term or bitext matching than to passage retrieval. So MMTEB **bitext mining** is the most relevant published signal for "a Turkish query finds the English-labelled concept". On that measure mE5-large-instruct (80.13) and bge-m3 (79.11) lead. Qwen3-0.6B (72.22) and EmbeddingGemma (64.40) are stronger at passage retrieval but weaker at bitext mining.
- **Static models and neutrality.** potion-multilingual-128M's bitext score (40.72) is about half of LaBSE's (76.35). A static model would therefore mostly help same-language paraphrase and typo matching, not cross-lingual neutrality. It must be labelled as "Model2Vec static distillation of bge-m3", never as "bge-m3".
- **Licence filter.** jina v3/v5 (CC BY-NC 4.0) are out for redistribution. EmbeddingGemma (Gemma terms, gated) should be avoided unless the owner accepts the terms. MIT or Apache-2.0 candidates: mE5 family, bge-m3, LaBSE, paraphrase-multilingual, gte-multilingual-base, Arctic 2.0, Qwen3-Embedding, Granite R2, potion, static-mrl.
- **Superseded models.**
  - Granite R1 (278m/107m) is replaced by R2 (2026-04-29). jina v3 is replaced by v5 (2026-02-18), still NC.
  - LaBSE and paraphrase-multilingual (2020-era) are clearly behind for retrieval. LaBSE is still competitive on bitext mining.

### Gaps
- No controlled CPU (Apple Silicon) encoding-throughput comparison across these models was found. Only vendor claims exist: static models 100–500x faster than mE5-small, and GPU throughput for Granite. This must be measured on the owner's Mac.
- No MMTEB bitext-mining or full mean(task) figures for Granite R2 or Arctic Embed 2.0 were found. IBM's R2 retrieval aggregate may not be comparable to the leaderboard's Retrieval column.
- EmbeddingGemma's licence status is unresolved: the HF metadata says "gemma" and gated, while Google's docs link an Apache-2.0 "Gemma 4" licence page. No Gemma-4-based embedding model was found.
- nomic-embed-text-v2-moe (Apache-2.0, HF repo created 2025-02-07 per [HF API](https://huggingface.co/api/models/nomic-ai/nomic-embed-text-v2-moe)) and KaLM small models were not researched.
- No published evaluation covers anything like acatalogue's 489-language label distribution. Most models claim roughly 50–200 languages.

## 2. Inference runtimes for local use without heavy dependencies

### Takeaway
The lightest route for a transformer model on a Mac is **ONNX Runtime + tokenizers + numpy**: a 21.5 MB plus 3.1 MB wheel set, with no torch. Several candidate models already publish ONNX files on the Hub. fastembed wraps the same stack but ships a narrow multilingual catalogue. llama.cpp/GGUF works for Qwen3-Embedding, EmbeddingGemma and Granite R2, but the Python binding compiles from source. Model2Vec's numpy inference is the only route that needs no neural runtime at all.

### Cited Findings
- **ONNX Runtime and tokenizers.** onnxruntime 1.30.0 (2026-09-10) depends on `flatbuffers, numpy>=1.21.6, packaging, protobuf`. Its macOS arm64 wheel (tagged `macosx_14_0_arm64`) is 21.5 MB — [PyPI](https://pypi.org/pypi/onnxruntime/json). tokenizers 0.23.2 has a 3.1 MB arm64 wheel — [PyPI](https://pypi.org/pypi/tokenizers/json)
- **Sentence-Transformers ONNX/OpenVINO backends.**
  - v3.2.0 (2024-10-10) added these backends. The release notes summarise CPU results as "~2.5x speedup at a cost of 0.4% accuracy", averaged over "4 models of various sizes, 3 datasets, and numerous batch sizes" — [ST v3.2.0](https://github.com/UKPLab/sentence-transformers/releases/tag/v3.2.0). My extraction could not tell whether this figure is FP32 or int8.
  - Dynamic int8 quantization configs exist for "arm64", "avx2", "avx512" and "avx512_vnni" — [ST v3.2.0](https://github.com/UKPLab/sentence-transformers/releases/tag/v3.2.0)
- **Published ONNX/GGUF artefacts and their sizes.** These are also rough download and RAM costs.
  - mE5-small ONNX: fp32 470 MB, O4 235 MB, `qint8_avx512_vnni` 118 MB — [HF files](https://huggingface.co/intfloat/multilingual-e5-small/tree/main/onnx)
  - bge-m3 ONNX: fp32 external data 2.27 GB — [HF files](https://huggingface.co/BAAI/bge-m3/tree/main/onnx)
  - granite-97m-r2: safetensors 195 MB, ONNX fp32 390 MB, `quint8_avx2` 98 MB, OpenVINO int8 98 MB — [HF files](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2/tree/main)
  - granite-311m-r2 ONNX: fp32 1.25 GB, `quint8_avx2` 313 MB — [HF files](https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2/tree/main/onnx)
  - potion-multilingual ONNX: 512 MB — [HF files](https://huggingface.co/minishlab/potion-multilingual-128M/tree/main)
  - The mE5 family, LaBSE, paraphrase-multilingual and Arctic 2.0 repos all carry the `onnx` tag — [HF](https://huggingface.co/intfloat/multilingual-e5-large-instruct), [HF](https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0)
- **fastembed.** Version 0.8.1 (2026-09-22) depends on onnxruntime, huggingface-hub, loguru, mmh3 and numpy — [PyPI](https://pypi.org/pypi/fastembed/json)
  - Its supported-models page lists these multilingual dense models: paraphrase-multilingual-MiniLM-L12-v2 (384d, 0.22 GB), paraphrase-multilingual-mpnet-base-v2 (768d, 1.0 GB), multilingual-e5-large (1024d, 2.24 GB) and jina-embeddings-v2-base-de — [fastembed models](https://qdrant.github.io/fastembed/examples/Supported_Models/)
  - Its sparse models are Qdrant/bm25, bm42 (all-MiniLM, English) and Splade_PP_en_v1 (English). jina-colbert-v2 is CC-BY-NC-4.0 — [fastembed models](https://qdrant.github.io/fastembed/examples/Supported_Models/)
- **llama.cpp / GGUF.**
  - Qwen3-Embedding-0.6B GGUF: Q8_0 639 MB, f16 1.20 GB — [HF files](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/tree/main)
  - EmbeddingGemma GGUF: Q8_0 334 MB, QAT Q4_0 278 MB — [ggml-org](https://huggingface.co/ggml-org/embeddinggemma-300M-GGUF/tree/main), [QAT](https://huggingface.co/ggml-org/embeddinggemma-300M-qat-q4_0-GGUF/tree/main)
  - Granite R2 can be converted with `convert_hf_to_gguf.py` and run with `llama-embedding` — [granite card](https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2)
  - llama-cpp-python 0.3.35 (2026-08-17) has no wheels on PyPI (sdist only; deps typing-extensions, numpy, diskcache, jinja2), so a pip install compiles C++ — [PyPI](https://pypi.org/pypi/llama-cpp-python/json)
- **Other runtimes.** EmbeddingGemma is supported by "sentence-transformers, llama.cpp, MLX, Ollama, transformers.js, LiteRT, … ONNX" — [Google blog](https://developers.googleblog.com/en/introducing-embeddinggemma/). A transformers.js ONNX build exists at onnx-community/embeddinggemma-300m-ONNX — [HF](https://huggingface.co/onnx-community/embeddinggemma-300m-ONNX)

### Inferences
- **Recommended stack.** `onnxruntime` + `tokenizers` + `numpy` needs no compiler or torch and is about 25 MB of wheels. Pooling and normalization are about 10 lines of numpy. This keeps acatalogue's "small dependencies" promise for any encoder model with a published ONNX file.
- **Quantized-file caveat.** Several published int8 ONNX files are x86-specific (`avx2`, `avx512_vnni`). On Apple Silicon, either use the fp32 ONNX or quantize with the "arm64" config. Either way, record that file as a distinct artefact (file hash plus a quantization label). An int8 variant gives slightly different vectors and must not be presented as the fp32 model.
- **llama.cpp.** It is attractive for decoder models such as Qwen3-0.6B or GGUF-only distributions. Its Python binding requires a local C++ build, which fits the "small dependencies" goal worse than ONNX Runtime.
- **macOS version.** The onnxruntime arm64 wheel tag (macOS 14) could exclude older Macs. Check the owner's OS version.

### Gaps
- No independent ONNX-vs-PyTorch CPU speed figures specific to Apple Silicon were found. The ST v3.2 summary does not name its hardware in my extraction.
- It is not verified whether fastembed can load Granite R2 or mE5-large-instruct through custom-model registration.

## 3. Vector search in or beside SQLite

### Takeaway
At acatalogue's scale (600 concept vectors, or ~122k label vectors), exact brute-force search in numpy takes about 0.4 ms (10k×768) to about 9 ms (100k×768) per query on a laptop-class CPU, per the researcher's own measurement below. No ANN index is needed, and no SQLite extension, which avoids macOS's extension-loading problem.
- **sqlite-vec.** The stable v0.1.9 (2026-03-31) is a sound option if SQL-native KNN with metadata filters is wanted. Its ANN indexes (rescore, IVF, DiskANN) are still alpha (v0.1.10-alpha.4, 2026-05-18).
- **sqlite-vss** is abandoned.
- **SQLite's own vec1** (v0.7, 2026-07-07) is a trained IVFADC/OPQ ANN index, aimed at larger static datasets.

### Cited Findings
- **sqlite-vec releases.**
  - v0.1.7 (2026-03-17) added proper DELETE and distance constraints for pagination; v0.1.9 (2026-03-31) fixed a DELETE bug.
  - v0.1.10-alpha.1 (2026-03-31) introduced "new ANN indexes: rescore, ivf (experimental), and DiskANN". alpha.4 is dated 2026-05-18.
  - The project is still pre-v1 — [sqlite-vec releases](https://github.com/asg017/sqlite-vec/releases). The README warns: "`sqlite-vec` is a pre-v1, so expect breaking changes!" — [README](https://github.com/asg017/sqlite-vec)
- **vec0 features.**
  - Metadata columns may be TEXT, INTEGER, FLOAT or BOOLEAN, at most 16. KNN filters accept `= != > >= < <=`; IS NULL, LIKE, GLOB, REGEXP or functions "will result in an error or incorrect results".
  - Partition keys: at most 4, with "~100s of vectors" per value. Auxiliary `+` columns: at most 16, stored but not filterable — [vec0 docs](https://alexgarcia.xyz/sqlite-vec/features/vec0.html)
- **Source-code limits and functions.**
  - Limits: `SQLITE_VEC_VEC0_K_MAX 4096`, `SQLITE_VEC_VEC0_MAX_DIMENSIONS 8192`, `VEC0_MAX_VECTOR_COLUMNS 16`, `VEC0_MAX_PARTITION_COLUMNS 4`.
  - Functions: `vec_quantize_int8`, `vec_quantize_binary`, `vec_int8`, `vec_bit`; distances L2, L1, cosine and Hamming.
  - ANN syntax on main: `INDEXED BY diskann(neighbor_quantizer=binary, n_neighbors=72)` and `INDEXED BY rescore(...)`, with options such as `oversample`, `quantizer` and `search_list_size` — [sqlite-vec.c](https://github.com/asg017/sqlite-vec/blob/main/sqlite-vec.c)
- **v0.1.0 (2024-08-01) announcement.**
  - Search was brute-force only.
  - SIFT1M (1M×128d) took 17–35 ms per query, against FAISS 10 ms and DuckDB 46 ms.
  - 1M×3072-d float vectors took 8.52 s per query, "beyond practical use"; bit vectors at the same scale took 124 ms.
  - `vec_quantize_binary()` was reported at ~5–10% quality loss for ~10x faster queries.
  - Platforms: macOS, Linux, Windows, WASM and Android — [v0.1.0 post](https://alexgarcia.xyz/blog/2024/sqlite-vec-stable-release/index.html)
- **Package.** The sqlite-vec 0.1.9 macOS arm64 wheel is 0.2 MB with no Python dependencies — [PyPI](https://pypi.org/pypi/sqlite-vec/json)
- **macOS caveat.** The docs say "The default SQLite library that is bundled with Mac operating systems do not include support for SQLite extensions", which surfaces as `AttributeError: … no attribute 'enable_load_extension'`. Workarounds: Homebrew Python (preferred), pysqlite3, or a custom SQLite. SQLite ≥3.41 is "recommended but not required" — [sqlite-vec Python docs](https://alexgarcia.xyz/sqlite-vec/python.html)
- **sqlite-vss.** "sqlite-vss is not in active development. Instead, my effort is now going towards sqlite-vec". It is Faiss-based; indexes are capped at 1GB, KNN has no filtering, indexes must fit in RAM, and there is no UPDATE — [sqlite-vss README](https://github.com/asg017/sqlite-vss)
- **SQLite vec1 (official).**
  - Announced 2026-02-26 by Dan Kennedy as "not ready for real use yet" — [SQLite forum](https://sqlite.org/forum/info/ceba048877c35c8e5a27e507d900a8f8727c4e546ad7f4eb74b52cea42a36db7)
  - v0.7 (2026-07-07) is "solid enough to stop calling it 'preview'" and adds an untrained RabitQ quantizer. The post calls it "in-the-ballpark competitive with most ANN vector-search implementations for static datasets" — [SQLite forum](https://sqlite.org/forum/info/aee74c239b7c36725ad5b563e0db94812730837792a569fd88b391c5e4824ae6)
  - It uses IVFADC with OPQ, float32 only, L2 and cosine, AVX2/NEON, and is built from a single `vec1.c`. The docs say "Testing is insufficient" — [vec1 docs](https://sqlite.org/vec1)
- **USearch.**
  - A single-header C++11 HNSW library with bindings in about 10 languages. Types: f64, f32, f16, bf16, i8, u8, fp8 variants and binary.
  - It supports exact search (`exact=True`) and memory-mapped "view" from disk, ships a SQLite extension, and is Apache-2.0. The Python binding is "< 1 MB" — [USearch](https://github.com/unum-cloud/usearch)
  - Version 2.26.2 (2026-08-31) has a 0.4 MB arm64 wheel and depends on numpy, tqdm and numkong — [PyPI](https://pypi.org/pypi/usearch/json)
- **hnswlib.** The last PyPI release is 0.8.0 (2023-12-03), with no wheels (sdist only) — [PyPI](https://pypi.org/pypi/hnswlib/json). faiss-cpu 1.15.1 has a 5.0 MB arm64 wheel — [PyPI](https://pypi.org/pypi/faiss-cpu/json)
- **scrydb** ("SQLite is Enough", Breuer, 2026-08-25). It uses FTS5 plus sqlite-vec with Qwen3-Embedding-8B (4096d).
  - Latency: binary Hamming search averaged 22.9 ms per query across 8 BEIR sets. Hamming plus int8 cosine rescoring took 164.5 ms, int8 cosine 822.5 ms, float cosine 2620 ms, and FTS5 BM25 193 ms.
  - Quality: Hamming+int8 rescoring nearly matches float, e.g. FiQA nDCG@10 0.649 vs 0.645.
  - The authors recommend it for "up to roughly a few million documents" — [scrydb](https://arxiv.org/html/2608.24060)
- **Own measurement (researcher, 2026-09-25).**
  - Setup: 4-vCPU Linux x86-64 container, 16 GB RAM, numpy 2.4.6, Python 3.11.15, SQLite 3.45.1. **Not a Mac.**
  - Method: float32 unit vectors, cosine via `X @ q` plus `argpartition` top-10, median single-query latency:

    | Vectors | 256d | 384d | 768d | 1024d |
    |---|---|---|---|---|
    | 1,000 | 0.026 ms | — | 0.022 ms | — |
    | 10,000 | 0.14 ms | — | 0.37 ms | — |
    | 100,000 | 1.6 ms | 3.2 ms | 8.9 ms | 11.0 ms |
    | 1,000,000 | 56 ms (1.0 GB) | 68 ms (1.5 GB) | 130 ms (3.1 GB) | — |

  - Batching 100 queries brought per-query time at 1M×768 down to 10.9 ms.
  - Script (reproducible): `X/=norm; s=X@q; idx=np.argpartition(-s,10)[:10]` over `rng.standard_normal((n,d),dtype=float32)`.

### Inferences
- **Memory at acatalogue's scale.** These figures are arithmetic, not sourced:

  | Label vectors (121,717) | Size |
  |---|---|
  | 1024d float32 | 499 MB |
  | 768d float32 | 374 MB |
  | 384d float32 | 187 MB |
  | 256d float32 | 125 MB |
  | 256d int8 | 31 MB |
  | 768-bit binary | 12 MB |

  The 600 concept vectors at 768d take 1.8 MB. All of these fit comfortably in RAM, and exact search stays in low milliseconds. Exact search also avoids ANN recall loss, which would complicate honest evaluation.
- **Suggested storage.** Store vectors as BLOBs in an ordinary table keyed by (model_id, item) and load them into numpy. This needs no extension. Use sqlite-vec only if SQL-side KNN with metadata filters (lang, scheme) becomes necessary, and gate it behind a capability check, because of the macOS extension-loading issue.
- **Scale thresholds.** Neither sqlite-vec's alpha ANN indexes nor vec1's trained IVF-PQ are justified below ~10^6 vectors. At that scale, even numpy brute force at 256–384d stays around 60–70 ms. USearch is the cleanest HNSW fallback if the catalogue ever grows past that.

### Gaps
- No Apple Silicon brute-force numbers were measured. Accelerate/NEON BLAS will differ from this container.
- Whether vec1 supports exact search, metadata filtering, and what licence it uses was not confirmed. The forum posts don't say.
- sqlite-vec's DiskANN/IVF recall and latency numbers were not found. They are alpha features.

## 4. Hybrid lexical + vector retrieval

### Takeaway
Fusing BM25 with dense retrieval gives large gains when the two are similarly strong, as on MIRACL (hybrid nDCG@10 0.581 vs 0.388 and 0.421). The gains shrink when the dense model is much stronger: bge-m3's dense+sparse gains +1.2, and scrydb's RRF won on only 1 of 8 BEIR sets. RRF with k=60 is a robust, parameter-light default. A tuned convex combination beats RRF once a small labelled set exists. The FTS5 + sqlite-vec pattern is well documented. Learned sparse retrieval adds little for acatalogue because FTS5 already supplies the lexical signal.

### Cited Findings
- **RRF (Cormack, Clarke & Büttcher, SIGIR 2009).** Score(d) = Σ 1/(k + r(d)), "where k = 60 was fixed during a pilot investigation and not altered during subsequent validation" — [RRF paper](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
  - Pilot MAP by k:

    | k | 0 | 10 | 20 | 60 | 80 | 100 | 500 |
    |---|---|---|---|---|---|---|---|
    | MAP | .2072 | .2123 | .2134 | .2145 | .2147 | .2142 | .2098 |

    The authors conclude k=60 is "near-optimal, but that the choice was not critical".
  - RRF "outperforms Condorcet, CombMNZ and the best system by 4% to 5% on average". It beat Condorcet 7 of 7 times (p≈0.008) and CombMNZ 6 of 7 (p≈0.04).
  - On LETOR 3, CombMNZ edged RRF (0.6107 vs 0.6051, p≈0.2) — [RRF paper](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
- **Convex combination vs RRF (Bruch, Gai & Ingber).**
  - "CC outperforms RRF in in-domain and out-of-domain settings", and RRF is "sensitive to its parameters".
  - CC is "sample efficient, requiring only a small set of training examples to tune its only parameter to a target domain", and its learning is "generally agnostic to the choice of score normalization" — [arXiv 2210.11934](https://arxiv.org/abs/2210.11934)
- **MIRACL.** 18 languages, ~77k queries and 700k+ judgments; the paper covers BM25, mDPR and hybrid baselines — [MIRACL](https://arxiv.org/abs/2210.09984). Dev averages from Pyserini — [Pyserini 2CR MIRACL](https://castorini.github.io/pyserini/2cr/miracl.html):

  | System | nDCG@10 | R@100 |
  |---|---|---|
  | BM25 | 0.388 | 0.777 |
  | mDPR | 0.421 | 0.797 |
  | BM25+mDPR hybrid | 0.581 | 0.895 |
  | mContriever | 0.431 | — |

- **bge-m3.**
  - Adding sparse to dense lifts MIRACL nDCG@10 from 69.2 to 70.4; adding multi-vector as well reaches 71.5. The "All" score weights dense 1, sparse 0.3, multi-vector 1 on MIRACL.
  - On MKQA (cross-lingual), sparse alone reaches only 45.3 R@100 against dense 75.1 — [bge-m3 paper](https://arxiv.org/html/2402.03216)
- **BEIR (NeurIPS 2021, 18 datasets).** "BM25 is a robust baseline", and "re-ranking and late-interaction-based models on average achieve the best zero-shot performances, however, at high computational costs". Dense models show "considerable room for improvement in their generalization" — [BEIR](https://arxiv.org/abs/2104.08663)
- **scrydb (2026).** With Qwen3-Embedding-8B, the "RRF hybrid search is the best-performing scrydb configuration on exactly one dataset, Touché" of 8 BEIR subsets — [scrydb](https://arxiv.org/html/2608.24060)
- **FTS5 + sqlite-vec in practice (Alex Garcia, 2024-10-02).**
  - Three patterns: "keyword-first" (FTS5 results first, via UNION ALL), RRF, and "re-rank by semantics" (FTS5 candidates re-ordered by vector distance).
  - The RRF SQL uses CTEs with `row_number() over (order by distance)` for vec0 and `row_number() over (order by rank)` for FTS5. It combines them with `coalesce(1.0/(:rrf_k + rank),0)*:weight` over a **FULL OUTER JOIN**, with `:k=10, :rrf_k=60, weights 1.0`.
  - Dataset and model: 14.5k NBC headlines with Snowflake Arctic Embed 1.5 (768d).
  - Caveat: "FTS5 tables perform a full search across the entire dataset everytime" — [Garcia, hybrid search](https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html)
- **FULL OUTER JOIN** support arrived in SQLite 3.39.0 (2022-06-25): "Add (long overdue) support for RIGHT and FULL OUTER JOIN" — [SQLite 3.39.0](https://www.sqlite.org/releaselog/3_39_0.html)
- **Re-ranking.** The bge-m3 card recommends "hybrid retrieval + re-ranking" and says cross-encoder re-rankers are more accurate than bi-encoders — [bge-m3 card](https://huggingface.co/BAAI/bge-m3). Qwen3-Reranker-0.6B is part of the same series. The embedding models are Apache-2.0, but the reranker repo's licence was not checked directly — [Qwen3 card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- **Learned sparse availability.** fastembed's SPLADE model (Splade_PP_en_v1) and bm42 are English — [fastembed](https://qdrant.github.io/fastembed/examples/Supported_Models/). Multilingual learned-sparse outputs exist in bge-m3 and gte-multilingual-base — [bge-m3](https://huggingface.co/BAAI/bge-m3), [gte](https://huggingface.co/Alibaba-NLP/gte-multilingual-base)

### Inferences
- **Signals to fuse.** acatalogue has three first-stage signals: FTS5 unicode61 BM25, FTS5 trigram, and dense. Label-level dense scores should be aggregated per concept, e.g. max similarity over a concept's labels, before fusion. RRF over the three ranked lists (k=60, weights 1) needs no score calibration, and each list is available as a SQL CTE or a Python list.
- **Known-item precision.** Keep Garcia's "keyword-first" behaviour for exact label matches. Most acatalogue queries are known-item label lookups, where FTS5 is already precise.
- **Tuning.** Once ≥50 judged queries exist, fit a convex combination (min-max normalised, one α per lexical/dense pair) on a dev split and report it next to RRF on a held-out split. The literature says CC should win, but the win must be shown on acatalogue data.
- **Learned sparse.** bge-m3 or gte-multilingual sparse adds a second model pass for small gains (+1.2 MIRACL nDCG@10) and is weak cross-lingually (MKQA 45.3). FTS5 already covers exact lexical matching. Not recommended.
- **Dense-only is plausible.** Given scrydb's result, a strong dense model alone could beat RRF on descriptive queries. Report dense-only, lexical-only and fused runs separately rather than assuming hybrid is best.

### Gaps
- I did not verify a multilingual SPLADE-style model with published MIRACL numbers.
- No published hybrid experiment on a short-label, many-language catalogue (as opposed to passage corpora) was found.

## 5. Evaluation: labelled query set, metrics, honest reporting

### Takeaway
Build a small in-house test collection with two parts:
- **Cross-lingual known-item queries**, generated from acatalogue's own multilingual labels with the query's language held out of the index.
- **Hand-written descriptive queries** with graded judgments, pooled from all systems.

Report MRR@10 and Recall@k for known-item queries and nDCG@10 for graded ones, per language and macro-averaged. Use paired randomization or bootstrap tests, not Wilcoxon or sign tests, and use enough queries: significance can mislead even at 50 topics.

### Cited Findings
- **Metrics convention.** MIRACL reports nDCG@10 and Recall@100 — [Pyserini 2CR](https://castorini.github.io/pyserini/2cr/miracl.html). BEIR frames evaluation as zero-shot across 18 heterogeneous datasets — [BEIR](https://arxiv.org/abs/2104.08663)
- **ranx.** Implements Hits, Hit Rate, Precision, Recall, F1, r-Precision, Bpref, RBP, MRR, MAP, DCG and NDCG; 25 fusion methods, including RRF, CombSUM, CombMNZ and Weighted Sum; six normalizations; and paired t-test (default), Fisher's randomization and Tukey HSD. It depends on Numba — [ranx](https://amenra.github.io/ranx/)
- **Significance tests (Smucker, Allan & Carterette, CIKM 2007).** Found "little practical difference between the randomization, bootstrap, and t tests". Wilcoxon and sign tests "should be discontinued" — [ACM](https://dl.acm.org/doi/10.1145/1321440.1321528) (summary via [Semantic Scholar/ACM search results](https://www.semanticscholar.org/paper/A-comparison-of-statistical-significance-tests-for-Smucker-Allan/3bf42fdbe24fe5aaa491266006d89bae53e99552))
- **Topic-set size.**
  - Voorhees & Buckley (SIGIR 2002): error rates were "larger than anticipated", so take care especially with few topics. TREC typically uses 50 topics — [ACM](https://dl.acm.org/doi/10.1145/564376.564432), [NIST](https://www.nist.gov/publications/effect-topic-set-size-retrieval-experiment-error)
  - "Topic set size redux" (SIGIR 2009): with real 50-topic sets, "statistically significant differences can be wrong, even when … accompanied by moderately large (>10%) relative differences" — [ACM](https://dl.acm.org/doi/10.1145/1571941.1572138)
- **LLM relevance labels (Thomas et al.).** LLM labels were "as good as human labellers", better than third-party workers "for a fraction of the cost". But "simple paraphrases" of prompts change accuracy, and gold labels are still needed — [arXiv 2309.10621](https://arxiv.org/abs/2309.10621)
- **Leaderboard caution.** MMTEB introduced a zero-shot English benchmark and task downsampling to keep ranking integrity — [MMTEB](https://arxiv.org/abs/2502.13595). Different sources' aggregates for the same model can disagree (Granite R1: 59.9 vs 52.2; see §1).

### Inferences
- **Query set A — cross-lingual known-item (automatic, stdlib only).**
  - For each concept c and each language L with a label, the query is label_L(c) and the only relevant item is c. To test semantic and cross-lingual ability rather than exact string match, index c **without** its language-L labels (leave-one-language-out).
  - Stratify by script and resource level: e.g. tr, zh, ar, hi, ru, sw, yo, am, plus a long-tail bucket. Sample e.g. 20–50 concepts per language.
  - Metrics: MRR@10, Success@1 and Recall@10. With 600 concepts and 489 languages, this yields thousands of queries cheaply.
- **Query set B — descriptive and paraphrase queries (manual).**
  - 50–100 queries in ~10 languages ("the study of living things", misspellings, Turkish inflected forms such as "fiziğin").
  - Graded 0/1/2 judgments, pooled from the top-10 of every system (LSA, FTS5, trigram, each dense model, each fusion). Metric: nDCG@10.
  - Any LLM-assisted judgments must be marked as such, with a human-checked subset.
- **Honest reporting.**
  - Freeze the test split before tuning fusion weights.
  - Report every system, including the LSA baseline and lexical-only runs.
  - Report per-language scores and the worst-language score, not just macro averages; this is a neutrality check.
  - Give 95% bootstrap CIs and paired randomization p-values.
  - State the exact model file, runtime and quantization.
  - Implement the metrics in ~40 lines of stdlib Python. ranx (Numba) can be an optional cross-check.

### Gaps
- No published benchmark matches acatalogue's task (short concept labels, 489 languages). External scores can only shortlist models, not decide between them.

## 6. Semantic 2-D layouts for the particle visualization

### Takeaway
For ~600 to ~120k points:
- **Python, numpy only:** keep a PCA/SVD layout computed from the new embeddings. acatalogue already has eigh-based SVD code.
- **Python, small dependencies:** openTSNE needs numpy, scipy and scikit-learn.
- **Browser:** run umap-js (Apache-2.0, seedable, step-wise API suited to animated particles) or DruidJS (20 methods including UMAP, t-SNE and PaCMAP, but LGPL-3.0).

umap-learn and PaCMAP pull in numba plus pynndescent or faiss, which is at odds with the small-dependency goal.

### Cited Findings
- **umap-learn** 0.5.12 (2026-04-08) requires `numpy, scipy, scikit-learn>=1.6, numba, pynndescent, tqdm` — [PyPI](https://pypi.org/pypi/umap-learn/json), [UMAP docs](https://umap-learn.readthedocs.io/en/latest/)
- **PaCMAP** 0.9.1 (2026-03-02) requires `faiss-cpu, numba>=0.57, numpy, scikit-learn` — [PyPI](https://pypi.org/pypi/pacmap/json)
  - It optimises neighbour, mid-near and further pairs to keep both local and global structure. FAISS replaced Annoy as the default nearest-neighbour backend. Defaults: n_neighbors 10, MN_ratio 0.5, FP_ratio 2.0, `init` "pca". Apache-2.0 — [PaCMAP](https://github.com/YingfanWang/PaCMAP)
- **openTSNE** 1.0.4 (2025-10-27) requires `numpy, scikit-learn, scipy` and has a 1.0 MB universal2 wheel — [PyPI](https://pypi.org/pypi/openTSNE/json)
- **umap-js** (PAIR-code) is Apache-2.0.
  - APIs: `fit`, `fitAsync` and step-wise `initializeFit()/step()/getEmbedding()`. Parameters: nNeighbors 15, minDist 0.1, nComponents, spread, a custom `distanceFn`, and a `random` PRNG for reproducibility.
  - It uses random rather than spectral initialisation ("comparable results for smaller datasets") and lacks specialised angular or sparse support — [umap-js](https://github.com/PAIR-code/umap-js)
- **DruidJS** implements 20 dimensionality-reduction methods, including PCA, MDS, t-SNE, UMAP, TriMap, PaCMAP and LocalMAP, with SIMD WebAssembly kernels and a pure-JS fallback. It runs in the browser and Node and is LGPL-3.0 — [DruidJS](https://github.com/saehm/DruidJS)

### Inferences
- **Proposed layout pipeline.**
  1. Compute a deterministic PCA (numpy SVD) seed layout server-side from the chosen model's L2-normalised concept vectors, and store it with a label such as "PCA of <model id>".
  2. Optionally refine it in the browser with umap-js, initialised from the PCA coordinates and using a fixed-seed PRNG and cosine `distanceFn`. Running it step-wise lets the particles animate toward the semantic layout.
  3. Label the refined view "UMAP (umap-js) of <model id>, seed N".
- **Cosine distances.** Because umap-js lacks angular specialisation, L2-normalise vectors first. Euclidean distance on unit vectors is then monotone in cosine distance (arithmetic identity).

### Gaps
- No published umap-js runtime numbers at 10^3–10^5 points were found.
- Whether PaCMAP exposes a random_state could not be confirmed from the README extraction.

## 7. Prioritized recommendation for acatalogue (model, library, index, fusion, evaluation)

### Takeaway
The recommendations, in priority order:
1. **Evaluation first.** Build the cross-lingual evaluation harness before changing models.
2. **Dense model.** Add a permissively licensed multilingual encoder through ONNX Runtime (no torch). The default is **intfloat/multilingual-e5-large-instruct** (MIT; best published bitext mining, 80.13). The challenger is **ibm-granite/granite-embedding-311m-multilingual-r2** (Apache-2.0; stronger vendor-reported retrieval, MRL, 32K context). Pick between them by acatalogue's own evaluation.
3. **Index.** Exact numpy search over vectors stored in SQLite.
4. **Fusion.** RRF (k=60) of FTS5 BM25 + FTS5 trigram + dense, with exact-label hits kept first. Move to a tuned convex combination once ≥50 judged queries exist.
5. **Layout.** Replace the LSA seed layout with PCA/umap-js of the new embeddings.

Keep LSA as the labelled baseline. Offer potion-multilingual-128M only as an explicitly labelled numpy-only fallback.

### Cited Findings
- **Evidence for mE5-large-instruct as default.**
  - Highest MMTEB bitext mining among compared open models (80.13) and mean 63.22 — [Qwen3 card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
  - "Best-performing publicly available model" in the MMTEB paper, and strong on mid-to-low-resource languages — [MMTEB](https://arxiv.org/abs/2502.13595), [HTML](https://arxiv.org/html/2502.13595)
  - Tatoeba (112 languages) 83.8 and MIRACL 65.7 — [mE5 report](https://arxiv.org/html/2402.05672)
  - MIT licence and an ONNX tag on the repo — [HF](https://huggingface.co/intfloat/multilingual-e5-large-instruct)
  - Limits: 512 tokens — [mE5 card](https://huggingface.co/intfloat/multilingual-e5-small). 559.9M parameters — [HF](https://huggingface.co/intfloat/multilingual-e5-large-instruct)
- **Evidence for Granite-311M-R2 as challenger.**
  - Apache-2.0, released 2026-04-29, 311M parameters. IBM reports 65.2 on 18 multilingual retrieval tasks.
  - MRL down to 256d loses only 63.9 → 63.5. Context is 32,768 tokens. It covers 200+ languages, with explicit cross-lingual training for 52 including Turkish and Chinese.
  - ONNX and OpenVINO files are published — [granite-311m-r2](https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2). ONNX fp32 is 1.25 GB — [files](https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2/tree/main/onnx)
- **Evidence for the small tier** (if laptop latency or disk is a problem). granite-97m-r2: 384d, IBM-reported 60.3 against mE5-small's 50.9 on the same aggregate, 98 MB int8 ONNX — [granite-97m-r2](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2), [files](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2/tree/main)
- **Evidence for the numpy-only tier.** potion-multilingual-128M: MIT, numpy+tokenizers runtime, 256d, but bitext mining only 40.72 — [card](https://huggingface.co/minishlab/potion-multilingual-128M), [pyproject](https://github.com/MinishLab/model2vec/blob/main/pyproject.toml)
- **Excluded models.** jina v3 and v5 are CC BY-NC 4.0 — [HF API](https://huggingface.co/api/models/jinaai/jina-embeddings-v5-text-small). EmbeddingGemma is under Gemma terms and gated — [HF API](https://huggingface.co/api/models/google/embeddinggemma-300m)
- **Runtime evidence.** onnxruntime has a 21.5 MB arm64 wheel, tokenizers 3.1 MB, torch 127.3 MB — [PyPI ORT](https://pypi.org/pypi/onnxruntime/json), [PyPI tokenizers](https://pypi.org/pypi/tokenizers/json), [PyPI torch](https://pypi.org/pypi/torch/json)
- **Index evidence.** The researcher's measurement gives ≈9 ms per query at 100k×768 and ≈3 ms at 100k×384 (§3). sqlite-vec needs extension loading, which macOS's default SQLite lacks — [sqlite-vec Python docs](https://alexgarcia.xyz/sqlite-vec/python.html). Its ANN features are alpha — [releases](https://github.com/asg017/sqlite-vec/releases)
- **Fusion evidence.**
  - RRF with k=60 is near-optimal and not critical — [RRF](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf). CC beats RRF with little tuning data — [Bruch et al.](https://arxiv.org/abs/2210.11934)
  - The MIRACL hybrid beats both components by a large margin — [Pyserini](https://castorini.github.io/pyserini/2cr/miracl.html). Hybrid is not always best with a very strong dense model — [scrydb](https://arxiv.org/html/2608.24060)
  - The SQL pattern needs FULL OUTER JOIN, available in SQLite ≥3.39 — [Garcia](https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html), [SQLite 3.39.0](https://www.sqlite.org/releaselog/3_39_0.html)
- **Evaluation evidence.** Use randomization, bootstrap or t-tests, not Wilcoxon or sign tests — [Smucker et al.](https://dl.acm.org/doi/10.1145/1321440.1321528). 50-topic significance can still mislead — [Voorhees 2009](https://dl.acm.org/doi/10.1145/1571941.1572138)
- **Provenance fit.** acatalogue already stores every vector under a model id so that methods sit side by side — [semantic.py](/home/user/acatalogue/acatalogue/semantic.py)

### Inferences
1. **P0 — Evaluation harness (stdlib).**
   - Build query sets A and B from §5, with MRR@10, Success@1, Recall@10 and nDCG@10, per-language and worst-language reporting, bootstrap CIs and a paired randomization test.
   - Run the existing LSA, FTS5 unicode61, FTS5 trigram and regex through it first, to get honest baselines.
2. **P1 — Dense model via `onnxruntime` + `tokenizers` + `numpy`.**
   - Embed concept texts (label + scope note + intro; mE5 truncates at 512 tokens) and every label in all 489 languages. Aggregate label hits per concept by max similarity.
   - Run mE5-large-instruct (1024d) and granite-311m-r2 (768d, or MRL-256d) through P0.
   - **Decision rule:** adopt the model with higher macro MRR@10 on set A and nDCG@10 on set B. If the difference is not significant, prefer granite-311m-r2, because it is smaller, supports MRL (256d int8 label vectors ≈31 MB rather than ≈499 MB for 1024d float32) and has a longer context.
   - **Provenance to record for every vector set:** HF repo, commit SHA, file SHA-256/512, runtime version, quantization, dimension or MRL truncation, pooling, normalisation and prompt prefix ("query: "/"passage: " or instruction).
   - On Apple Silicon, use fp32 ONNX or an arm64-quantized export, labelled as such. Never present a quantized, truncated or distilled variant as the original.
3. **P2 — Index.** Store float32 (or float16/int8, labelled) vectors as BLOBs in SQLite and search exactly in numpy (low ms at ≤122k vectors). Add sqlite-vec 0.1.9 vec0 (metadata `lang`, partition by `scheme`) only as an optional, capability-checked accelerator. Do not adopt sqlite-vec 0.1.10-alpha ANN or vec1 at this scale.
4. **P3 — Fusion.**
   - Use RRF (k=60, weights 1) over FTS5-unicode61, FTS5-trigram and dense lists, each truncated at e.g. 50. Exact label matches go first ("keyword-first").
   - After ≥50 judged queries, tune a min-max convex combination on a dev split and report RRF, CC, dense-only and lexical-only on the frozen test split.
   - Skip learned sparse (SPLADE, bge-m3 sparse).
5. **P4 — Visualization.** Replace the LSA 2-D seed with a PCA of the adopted model's vectors. Optionally refine in-browser with umap-js (seeded, cosine via unit vectors, step-wise animation). Label the method, model and seed in the UI.
6. **P5 — Optional later work.**
   - A cross-encoder re-ranker (e.g. Qwen3-Reranker-0.6B; check its licence first) over the top-20 fused candidates, if P0 shows ranking errors among near-misses.
   - potion-multilingual-128M as a labelled "no-ONNX" fallback tier.
   - USearch only if vectors exceed ~10^6.

### Gaps
- The default versus challenger decision cannot be settled from published data. Bitext-mining scores for Granite R2 and Apple Silicon encode latency for both models are missing. Both must be measured locally.
- The one-time cost of embedding ~122k labels plus ~600 texts on a Mac CPU with a 560M versus a 311M model is unmeasured. It is expected to be tolerable because labels are short, but no source was found.
- How well any model handles the long tail of acatalogue's 489 label languages is unknown. Most models document 50–200 languages. Report per-language results and flag out-of-coverage languages rather than claiming support.
