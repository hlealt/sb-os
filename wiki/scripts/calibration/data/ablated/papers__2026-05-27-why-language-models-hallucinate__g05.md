<!-- SILVER-ABLATION FIXTURE -- DO NOT INGEST. grade=0.05 deleted=3 from=3-resources/knowledge-base/wiki/sources/papers/2026-05-27-why-language-models-hallucinate.md schema=silver-ablation/1 -->
---
type: source
created: 2026-05-27
last-touched: 2026-05-27
raw: "[[2026-05-27-why-language-models-hallucinate.md]]"
url: https://arxiv.org/html/2509.04664v1
author: "Adam Tauman Kalai, Ofir Nachum, Santosh S. Vempala, Edwin Zhang"
related:
  - "[[ai-hallucination.md]]"
  - "[[calibration.md]]"
  - "[[is-it-valid-reduction.md]]"
  - "[[singleton-rate.md]]"
  - "[[evaluation-induced-hallucination.md]]"
tags: [source]
---

# Why Language Models Hallucinate

OpenAI / Georgia Tech paper arguing that hallucinations are not mysterious but a statistically inevitable consequence of the pretraining objective, and that they persist after post-training because the dominant evaluation benchmarks reward confident guessing over honest abstention.

## Substance

- The paper's thesis is that language models hallucinate because both the training and the evaluation procedures reward guessing over acknowledging uncertainty; hallucinations originate as ordinary errors in binary classification, not as a mysterious property of neural text generation.[^1]
- Its central technical move is the [[is-it-valid-reduction.md]]: it reduces generative error to a supervised binary-classification problem ("Is this a valid output?") and proves a lower bound — the generative error rate is at least twice the Is-It-Valid misclassification rate (`err ≥ 2·err_iiv`).[^1] This connection between unsupervised density estimation and supervised classification is presented as novel, and it shows that even error-free training data would still yield a base model that generates errors.[^1]
- The reduction applies generally — to reasoning models, search/retrieval-augmented models, and any architecture — because it does not depend on next-word prediction or the Transformer; it treats the model purely as a probability distribution over strings.[^1] The "autocomplete" framing is dismissed as no more significant than the fact that humans also produce one word at a time.[^1]
- [[calibration.md]] is the hinge of the pretraining argument: the paper shows the miscalibration term δ is the magnitude of the derivative of the cross-entropy loss with respect to a probability-rescaling factor, so a well-trained, locally optimal base model is necessarily near-calibrated — and a calibrated model that errs is mathematically forced, while a model that never errs must be badly miscalibrated.[^1] Empirically, base models are observed to be calibrated, whereas reinforcement-learning post-training can break calibration.[^1]
- For arbitrary facts — facts with no learnable pattern, such as individual birthdays — the lower bound is the [[singleton-rate.md]]: the fraction of training facts that appear exactly once. If 20% of birthday facts appear once in pretraining, a base model is expected to hallucinate on at least ~20% of birthday questions.[^1] The singleton rate is built on Turing's missing-mass estimator (the share of singletons estimates the unseen-event probability).[^1]
- A second error family is "poor models": when the model class cannot represent the concept (the paper's worked example is the classic two-word-context trigram model, which must err at least half the time on gendered-pronoun completions, Corollary 2).[^1] Letter-counting failures ("how many Ds in DEEPSEEK") are diagnosed as a poor-model / tokenization issue — reasoning models like DeepSeek-R1 count letters reliably because chain-of-thought spells the word out, while token representations (D/EEP/SEE/K) obscure individual characters.[^1] Additional error sources named: computational hardness, distribution shift (out-of-distribution prompts), and GIGO (errors replicated from a noisy corpus).[^1]
- The paper's distinctive claim is [[evaluation-induced-hallucination.md]]: hallucinations survive post-training because the field's primary benchmarks use binary 0-1 grading that awards no credit for "I don't know" (IDK), so abstaining is strictly sub-optimal and an overconfident guess maximizes expected score (Observation ).[^1] A meta-evaluation of ten popular benchmarks (GPQA, MMLU-Pro, SWE-bench, MATH, and others) finds the vast majority use binary grading with no IDK credit; therefore adding more hallucination-specific evaluations cannot fix the problem while the dominant evaluations still penalize honesty.[^1]
- The proposed fix is socio-technical, not a new benchmark: modify the scoring of the mainstream, leaderboard-dominating evaluations to state an explicit confidence target in each question's instructions (e.g., "answer only if you are >t confident; a wrong answer costs t/(1−t) points, a correct answer scores 1, IDK scores 0").[^1] This makes one model simultaneously optimal across thresholds — a property the paper names 's behavioral variant ("behavioral calibration"): output the most useful answer in which the model is at least t confident, auditable by comparing accuracy and error rates across thresholds.[^1]
- Limitations the authors flag: the analysis only covers plausible strings (ignores nonsense), models a single factual question rather than open-ended generation, and treats correct/incorrect/IDK as a "false trichotomy"; search and reasoning are explicitly not panaceas because binary grading still rewards guessing whenever retrieval fails.[^1]

## Notable quotes

[^1]

> Hallucinations need not be mysterious—they originate simply as errors in binary classification.[^1]

> Language models are optimized to be good test-takers, and guessing when uncertain improves test performance.[^1]

> Under binary grading, abstaining is strictly sub-optimal.[^1]

## Methodology

- **Type:** Theoretical paper with formal proofs (computational learning theory), plus a small empirical meta-evaluation of benchmark grading and illustrative model probes.
- **Core formal objects:** the Is-It-Valid (IIV) binary-classification problem (50/50 mixture of valid examples and uniformly random errors); the reduction theorem `err ≥ 2·err_iiv − |V|/|E| − δ` (Corollary 1, generalized with prompts in Theorem 1); the Arbitrary Facts model and singleton-rate bound (Theorem 2); the pure-multiple-choice bound (Theorem 3); the binary-grader optimality result (Observation 1). Full proofs in Appendices A–F.[^1]
- **Calibration argument:** δ (miscalibration at threshold 1/|E|) is shown to equal the magnitude of the loss derivative under probability rescaling, justifying small δ for any model class powerful enough to approximate rescaling under cross-entropy.[^1]
- **Empirical illustrations (not the contribution):** repeated probes of state-of-the-art models on the author's birthday, the "Ds in DEEPSEEK" count, and Adam Kalai's dissertation title (Table 1) across GPT-4o/ChatGPT, DeepSeek-V3, DeepSeek-R1, Llama, Meta AI, and Claude 3.7 Sonnet; a calibration figure for a GPT-4 base model.[^1]
- **Meta-evaluation:** Table 2 classifies ten mainstream benchmarks by scoring method, whether grading is binary, and whether IDK earns credit — finding nearly all binary with no IDK credit.[^1]
- **Limitations (author-stated):** plausible-strings-only scope; single-factual-question framing; correct/incorrect/IDK "false trichotomy"; search/RAG and reasoning do not escape the incentive problem.[^1]

## Connections

- Extends [[ai-hallucination.md]] — this is the primary academic source for the structural claim the page currently cites only secondhand; it reframes hallucination as binary-misclassification error with a calibration-based inevitability proof for base models.
- Introduces [[calibration.md]], [[is-it-valid-reduction.md]], [[singleton-rate.md]], and [[evaluation-induced-hallucination.md]] as the paper's core concepts.
- Bears on [[retrieval-augmented-generation.md]] — the paper argues RAG suppresses but cannot eliminate hallucination, because binary grading still rewards guessing when retrieval fails.
- Touches [[active-learning.md]] and [[self-supervised-learning.md]] — the reduction links self-supervised density estimation to supervised classification; active querying of a validity oracle is cited as a related (statistically efficient but compute-expensive) mitigation line.

---

## My take

## Sources

[^1]: [[2026-05-27-why-language-models-hallucinate.md]]
