---
id: correction-classes
scope: wave-rankers, ingest-verifiers
---

# Wave-Figure Correction Classes

Reference catalogue for wave rankers (Step 3 / Step 7a) and ingest verifiers (Step 7). Each class is a named failure mode — a way a wave-returned figure can turn out wrong when the ingest checks it against the captured source. Wave rankers MUST watch for signals of each class during discovery; ingest verifiers MUST check each class against the captured source before accepting a figure as confirmed.

A figure that matches a class below is UNVERIFIED until the ingest confirms it is absent from the source. Any figure that cannot be confirmed in the captured source MUST be flagged, not silently carried.

## Correction Classes

| Class | Definition | What to check |
|-------|------------|---------------|
| **cross-attribution** | Figure is real but belongs to a different entity than stated. | Confirm the named entity in the sentence that contains the figure matches the entity the wave attributed it to. |
| **figure transposition** | Two figures from the same source are swapped (e.g., revenue assigned to earnings and vice versa). | Re-read the surrounding sentence and table header; confirm which metric label the source attaches to which value. |
| **polarity inversion** | Sign is wrong — a loss reported as a gain, a decline as a growth. | Check the literal sign in the source text; watch for parentheses, minus signs, and "decline/fell/contracted" language. |
| **stance inversion** | A bearish/negative analytical conclusion is returned as bullish/positive, or vice versa. | Re-read the source's conclusion sentence; confirm the wave's characterization matches the source's stated direction. |
| **wrong-period document** | Figure is real but sourced from a different reporting period than the one the wave named (e.g., FY2023 figure attributed to FY2024). | Confirm period label in the source table header or introductory sentence matches the wave-stated period. |
| **wrong-vintage** | Figure is from an older revision of the source (e.g., a preliminary estimate later restated). | Check the source page's publication or revision date; flag if a newer revision of the same document exists. |
| **analyst-gloss absorption** | Figure originates in an analyst's commentary or interpretation, not in the primary source the wave cited. | Confirm the figure appears in the primary document itself, not only in a secondary analyst layer wrapping it. |
| **editorial-assembly attribution** | A figure assembled by a journalist or editor from multiple sources is attributed to a single named source. | Verify the figure appears verbatim in the named source, not assembled across sources in the article's text. |
| **contract-texture invention** | A specific contract term, clause, or numeric threshold is stated that does not appear in the cited document. | Grep/scan the source text for the exact term or number; if absent, the figure is fabricated. |
| **derived-figure-as-stated** | A derived or calculated figure (e.g., a ratio, a growth rate) is presented as if it were a stated figure in the source. | Confirm the figure appears as-printed in the source; derivations that appear only in the wave's reasoning are NOT stated figures. |
| **chart-only figures** | The figure lives in a chart image in the source document, not in the document's text or tables. | Scan the source text and accessible tables; if the figure appears only in an image chart, it is chart-only and unconfirmable from text. |
| **video-embedded figures** | The figure appears only in a video or audio recording embedded in or linked from the source page, not in the page text. | Confirm the figure appears in the page's text content; flag if it appears only in a video/audio embed. |
| **paywall-truncated raw** | The captured source is a truncated preview; the figure appears only in the paywalled portion not captured. | Check the captured raw for a paywall cut-off marker or truncation; confirm the figure is within the captured portion. |
| **aggregator-attribution failure** | An aggregator (e.g., data terminal, news feed) attributed a figure to an underlying source, but the underlying source does not contain it. | Confirm the figure in the underlying primary source, not just in the aggregator. |
| **fabricated cross-quarter sequence** | A multi-quarter trend or sequence of figures is returned that cannot be assembled from the cited source alone (e.g., only one quarter is present in the source). | Verify EACH figure in the sequence appears in the cited source for its stated period; a sequence requires per-period confirmation. |
| **topic conflation** | A figure for one topic, sector, or product line is attributed to another because the source discusses both. | Confirm the sentence carrying the figure names the same topic/segment the wave attributed it to. |
| **landing-vs-document gap** | The wave's URL resolves to a landing page (press release hub, investor-relations index) rather than to the actual document that contains the figure. | Verify the captured raw is the document itself, not a landing page; follow the link to the primary document if needed. |
| **source-internal inconsistency** | The cited source contains two conflicting values for the same metric and period; the wave returned one without flagging the conflict. | Scan the source for duplicate statements of the same metric; flag any internal conflict rather than choosing one value. |
| **wrong-operator attribution** | A figure for one operating entity is attributed to a parent or subsidiary, or to a joint-venture partner. | Confirm the entity named in the source sentence matches the entity the wave attributed the figure to. |
| **speculative wave framing** | The wave returned a figure that the source frames as a forecast, target, or analyst estimate, attributed as if it were a reported result. | Confirm whether the source presents the figure as reported actuals or as a projection/target/estimate; label accordingly. |
| **year attribution** | The figure's calendar year is misread — e.g., a fiscal year ending March 2024 is labeled FY2023 by the wave. | Confirm the fiscal year end convention used in the source; reconcile fiscal-year labels with calendar-year end dates. |
| **two-sided-on-ingest** | The captured source carries both FOR-side and AGAINST-side material on the anchor claim — a disconfirm source that also contains confirmatory evidence, or vice versa. | Fold both sides into the ingest return; flag the source explicitly as two-sided so the agent does not treat it as pure evidence-against or pure evidence-for. |
