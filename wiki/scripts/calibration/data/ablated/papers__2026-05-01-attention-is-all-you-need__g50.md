<!-- SILVER-ABLATION FIXTURE -- DO NOT INGEST. grade=0.5 deleted=23 from=3-resources/knowledge-base/wiki/sources/papers/2026-05-01-attention-is-all-you-need.md schema=silver-ablation/1 -->
---
type: source
created: 2026-05-25
last-touched: 2026-05-25
raw: "[[2026-05-01-attention-is-all-you-need.md]]"
url: https://arxiv.org/html/1706.03762v7
author: "Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Łukasz Kaiser, Illia Polosukhin"
related: []
tags: [source]
---

# Attention Is All You Need

## Substance

- Proposes the , a sequence-transduction architecture built solely on attention, dispensing with recurrence and convolution entirely.[^1] This removes the sequential-computation constraint that an  imposes (hidden state at step $t$ depends on step $t-1$), unlocking far more parallelization within training examples.[^1]
- Retains the standard  structure: a -layer encoder maps the input symbol sequence to continuous representations, and a 6-layer decoder generates the output one token at a time, auto-regressively consuming previously generated symbols.[^1]
- The core mechanism is  (intra-attention), which relates different positions of a single sequence to compute a representation of that sequence, connecting any two positions with a constant number of operations ($O()$ maximum path length) versus $O(n)$ for recurrence.[^1] The paper implements it as "scaled dot-product attention" — dot products of queries with keys, scaled by /\sqrt{d_k}$ before softmax — where the scaling counteracts vanishing softmax gradients at large key dimension.[^1]
- Achieves new state-of-the-art translation quality at a fraction of prior training cost: 28.4 BLEU on WMT 2014 English-to-German (> BLEU over prior best, including ensembles) and 41.8 BLEU single-model on English-to-French, after 3.5 days on eight P100 GPUs.[^1] The base model trains in ~12 hours and surpasses all prior published single models and ensembles.[^1]
- Demonstrates generalization beyond translation: a 4-layer Transformer applied to English constituency parsing outperforms most prior models even in the small-data (40K-sentence) regime where RNN sequence-to-sequence models had failed.[^1]
- Authored at Google Brain and Google Research; Noam Shazeer () proposed scaled dot-product attention, multi-head attention, and the parameter-free position representation, while Ashish Vaswani () and Illia Polosukhin designed and implemented the first Transformer models.[^1]

## Methodology

-  WMT 2014 English-German (~4.5M sentence pairs, ~37K shared byte-pair vocabulary) and the larger WMT 2014 English-French (36M sentences,  word-piece vocabulary); batches grouped by approximate sequence length (~25K source +  target tokens each).[^1]
-  one machine with 8 NVIDIA P100 GPUs; base model 100K steps (~12h), big model 300K steps (~3.5 days).[^1]
-  Adam ($\beta_1{=}0.9$, $\beta_2{=}0.98$) with a warmup-then-inverse-square-root learning-rate schedule (4000 warmup steps).[^1]
-  residual dropout ($P_{drop}{=}0.1$ base) and label smoothing ($\epsilon_{ls}{=}0.1$), the latter hurting perplexity but improving accuracy and BLEU.[^1]
-  vary attention heads, key/value dimensions, model depth/width, dropout, and positional encoding; single-head attention is  BLEU worse than the best head count, and too many heads also degrades quality.[^1]

## Connections

- Foundational substrate for [[llm.md]] — the auto-regressive next-token predictor at the center of modern large language models is the Transformer decoder introduced here.[^1]
- The Transformer's self-attention is the architecture later trained via [[self-supervised-learning.md]] at scale; this paper supplies the architecture, not the training paradigm.[^1]
- The variable-dimension subspaces and parallelism that [[scaling-laws.md]] exploit depend on the parallelizable, recurrence-free design proposed here.[^1]
- [[in-context-learning.md]] — the prompt-as-context behavior of later LLMs runs on the attention mechanism defined in this paper.[^1]
- Authored at Google Brain (lineage now under [[google-deepmind.md]]); cites the sparsely-gated [[mixture-of-experts.md]] layer as a contemporaneous efficiency direction.[^1]

---

## My take

## Sources

[^1]: [[2026-05-01-attention-is-all-you-need.md]]
