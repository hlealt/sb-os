<!-- SILVER-ABLATION FIXTURE -- DO NOT INGEST. grade=0.05 deleted=5 from=3-resources/knowledge-base/wiki/sources/papers/2026-05-07-the-rising-costs-of-training-frontier-ai-models.md schema=silver-ablation/1 -->
---
type: source
created: 2026-05-25
last-touched: 2026-05-25
raw: "[[2026-05-07-the-rising-costs-of-training-frontier-ai-models.md]]"
url: https://arxiv.org/html/2405.21015v2
author: "Ben Cottier, Robi Rahman, Loredana Fattorini, Nestor Maslej, Tamay Besiroglu, David Owen"
related:
  - "[[epoch-ai.md]]"
  - "[[ai-training-cost-trends.md]]"
  - "[[frontier-model.md]]"
tags: [source]
---

# The rising costs of training frontier AI models

Epoch AI cost model estimating that the amortized cost of training top-tier AI models has grown ~2.4x per year since 2016, projecting billion-dollar training runs by 2027 and a concentration of frontier development among the best-funded organizations.

## Substance

- The paper builds a detailed cost model for training [[frontier-model.md]]s, defined as models in the top 10 most compute-intensive at their release date, using three complementary approaches that account for hardware, energy, cloud rental, and staff costs.[^1]
- The headline result: [[ai-training-cost-trends.md]] show the amortized cost of the most compute-intensive training runs growing at 2.4x per year since 2016 (90% CI: 2.0x–); the cloud-rental approach independently yields a similar 2.5x/year rate, validating the trend.[^1]
- Excluding Google TPUs (whose costs are estimated rather than priced) raises the growth rate to 3.0x per year, because TPU-trained models carry artificially low hardware costs.[^1]
- The most expensive publicly announced runs to date are [[openai.md]]'s [[gpt-4.md]] at $40M amortized and 's [[gemini-models.md|Gemini Ultra]] at $30M amortized; extrapolating the 2.4x trend implies a ~$1 billion training run by the start of 2027.[^1]
- The preferred method, [[compute-cost-amortization.md]], spreads depreciated hardware value over the final training run (depreciating at 0.14 orders of magnitude per year, the rate of ML GPU price-performance improvement) rather than counting full purchase price; acquisition cost is one-to-two orders of magnitude higher (GPT-4's hardware cost ~$800M to acquire vs $40M amortized).[^1]
- Component breakdown of amortized hardware-plus-energy cost: ~44% AI accelerator chips, ~29% rest-of-server, ~17% cluster-level interconnect, ~9% energy — though energy's small cost share understates the rapidly growing power-capacity requirement.[^1]
- A third, deeper approach for four models ([[gpt-3.md]], [[opt-175b.md]], [[gpt-4.md]], [[gemini-models.md|Gemini Ultra]]) adds R&D staff costs over the whole development process (experiments, evaluation, fine-tuning): R&D staff are 29–49% of total cost with equity included, 19–33% excluding equity; computing hardware is 47–64%, energy 2–6%.[^1]
- The work draws on Epoch AI's Notable AI Models database (796 models, 276 filtered to the large-scale era, 41 frontier models analyzed) and a custom dataset of 142 historical hardware-price entries across 24 hardware models.[^1]
- Power capacity is flagged as a coming bottleneck — Gemini Ultra's cluster drew ~35 MW, and the trend projects a 1 GW training run by 2028 (comparable to a large power plant).[^1]

## Methodology

- **Frontier selection.** Top-10-by-compute-at-release; 41 models qualify. Robustness tested against top-N (N=3,5,20) and quantile/trend-distance alternatives — results are similar except the trend-distance method, which flattens the curve.[^1]
- **Amortization.** Hardware value depreciates at r=0.14 OOMs/year; amortized cost ≈ start-value-per-chip × (training chip-hours / hours-per-year) × r·ln(10). Chip-hours substitute for separately-estimated training time and chip count.[^1]
- **Staff cost.** Total annual compensation sampled from log-normal distributions (base salary 90% CI $140K–$160K, equity $35K–$490K, 1.25–1.4x overhead), informed by levels.fyi and aipaygrad.es; FTE workload per contributor sampled at a median ~20%.[^1]
-  No public sale prices exist, so [[tensor-processing-unit.md]] cost is the geometric mean of a bill-of-materials low estimate and an equivalent-GPU-price high estimate (~$5,000 per TPU across versions).[^1]
- **Limitations the authors state.** Reliance on public data; neglected costs (data-center infrastructure beyond the training cluster, data acquisition); uncertainty from depreciation and pricing assumptions; limited generality of the selected-frontier trend; possible large unpredictable hardware/software efficiency gains.[^1]

## Connections

- Updates [[ai-economic-concentration.md]] — supplies the quantitative cost driver (2.4x/year, >$100M total development cost) behind the concentration-of-frontier-development thesis.
- Cites [[dario-amodei.md]]'s claim that a single training run would approach a billion dollars in 2024 — empirical anchor that the paper's trend may be conservative.
- Relates to [[scaling-laws.md]] — the cost growth is the financial face of the compute-scaling regime that scaling laws describe.
- New entities introduced: [[epoch-ai.md]] (research org / database), [[openai.md]], [[google-deepmind.md]], [[nvidia.md]] (developers/hardware), and the model pages [[gpt-4.md]], [[gemini-models.md|Gemini Ultra]], [[gpt-3.md]], [[opt-175b.md]].

## Notable quotes

> "the amortized cost to train the most compute-intensive models has grown precipitously at a rate of $2.4\times$ per year since 2016"[^1]

> "If the trend of growing development costs continues, the largest training runs will cost more than a billion dollars by 2027, meaning that only the most well-funded organizations will be able to finance frontier AI models."[^1]

> "Dario Amodei, CEO of the AI lab Anthropic, has stated that frontier AI developers are likely to spend close to a billion dollars on a single training run this year, and up to ten billion-dollar training runs in the next two years"[^1]

---

## My take

## Sources

[^1]: [[2026-05-07-the-rising-costs-of-training-frontier-ai-models.md]]
