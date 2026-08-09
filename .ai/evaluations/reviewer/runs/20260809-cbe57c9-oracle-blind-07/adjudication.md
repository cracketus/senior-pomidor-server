# Adjudication: 20260809-cbe57c9-oracle-blind-07

Verdict: `CORPUS_INVALID_RERUN_REQUIRED`

The clean risk-routed run confirms that the large historical diffs are not a stable evaluation
fixture. They repeatedly produce different supported findings outside the versioned oracle, while
still missing other expected details. Adding each newly observed issue to the answer set would make
the benchmark depend on prior model output rather than a complete independently adjudicated corpus.

The one-to-one mapping is frozen and intentionally leaves new historical findings and duplicate
evidence restatements unmapped. This run fails HIGH recall and false-positive gates and must not be
published.

Corpus v2 replaces the three broad historical feature diffs with small pinned dependency-update diffs;
RV-02 remains unchanged. The six seeded mutations remain unchanged. Oracle v6 contains their core,
distinct root causes and consolidates evidence gaps that share one required change. A complete fresh
blind run is mandatory.
