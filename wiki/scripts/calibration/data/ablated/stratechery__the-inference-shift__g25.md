<!-- SILVER-ABLATION FIXTURE -- DO NOT INGEST. grade=0.25 deleted=10 from=3-resources/knowledge-base/wiki/sources/stratechery/the-inference-shift.md schema=silver-ablation/1 -->
---
type: source
created: 2026-06-14
last-touched: 2026-06-14
raw: "[[the-inference-shift.md]]"
url: https://stratechery.com/2026/the-inference-shift/
author: "Ben Thompson"
related:
  - "[[agentic-inference.md]]"
  - "[[answer-inference.md]]"
  - "[[ai-inference.md]]"
tags: [source]
---

# The Inference Shift

## Substance

- [[nvidia.md]]'s GPU advantage rests on three capabilities — high compute for the prefill step, abundant [[high-bandwidth-memory.md]] for the [[kv-cache.md]] and model weights, and chip-to-chip networking to pool memory across chips — and that flexibility lets one GPU fleet do both training and inference (e.g. Anthropic contracting all of SpaceX's Colossus 1, over 220,000 GPUs / , repurposed from training).[^1]
- Inference decomposes into prefill (parallel, compute-bound) and two interleaved decode steps (serial, memory-bandwidth-bound); for every token generated both the growing [[kv-cache.md]] and the full model weights must be read, making decode the latency-critical, memory-bound part of .[^1]
- [[cerebras-systems.md]] takes the opposite approach with the [[wafer-scale-engine-3.md]]: wiring across the wafer's scribe lines makes a whole wafer one chip, yielding 44GB of on-chip SRAM at 21 PB/s — roughly half an H100's memory but ~6,000× its bandwidth — blisteringly fast while model and KV cache fit on-chip, but uneconomic the moment they don't (whole-wafer yields drive cost up).[^1]
- The essay's core distinction is [[answer-inference.md]] (providing an answer with a human waiting, where token speed dominates — the market for [[cerebras-systems.md]] and ) versus [[agentic-inference.md]] (doing a task with no human in the loop, where memory capacity, state and history dominate and latency barely matters).[^1]
- Because agentic work runs without a human waiting, [[agentic-inference.md]] trades speed for capacity: it favors a memory hierarchy (active KV cache, host memory/SSD, databases, embeddings, object stores) wrapped around the model, using slower/cheaper memory such as traditional DRAM and merely "good enough" compute — gradually unbundling the [[gpu.md]].[^1]
- Implications: [[nvidia.md]]'s latency premium looks less worth paying for agentic inference (its own Dynamo framework disaggregates inference and adds standalone memory/CPU racks in response); China already has everything it needs for agentic inference (fast-enough GPUs/CPUs, DRAM, drives) and lacks only training compute; and slower, older-node chips make space data centers more viable (cooler, radiation-tolerant, lower-power, more reliable).[^1]
- Reframing 's "Moore's Law is Dead": where Huang means future speedups come from systems innovation, Thompson argues agents acting without humans make [[moores-law.md]] not matter at all — the compute we already have is good enough.[^1]

## Notable quotes

- "There is a difference between providing an answer — what I will call 'answer inference' — and doing a task — what I will call 'agentic inference.' ... in the long run, I think the architecture for 'agentic inference' will look a lot different, not just from Cerebras' approach, but from the GPU approach as well."[^1]

## Connections

- Extends [[ai-inference.md]] by splitting inference into answer vs agentic types with different optimal hardware, refining the "inference must be metro-sited for latency" picture (latency-insensitive for agentic work).[^1]
- Sits opposite the merchant-GPU-dominance trajectory on [[gpu.md]] and [[nvidia.md]] — agentic inference unbundles the GPU toward memory-centric, lower-cost architectures.[^1]
- Adds a latency-insensitivity rationale alongside [[ai-training-workload.md]] siting, and gives [[cerebras-systems.md]] / [[wafer-scale-engine-3.md]] their structural place (answer inference, on-chip-memory-bound).[^1]

---

## My take

---

## Sources

[^1]: [[the-inference-shift.md]]
