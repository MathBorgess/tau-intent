# Audit of four empty recall results

All four empty results match the published history at query time. The audit found no defect in query selection. It found no path mismatch, moved symbol, or filter for the current stage.

Both models query history before their first publication in M06. Those two queries have no published entries. Luna later publishes no M06 entries, so its M11 query also has no history.

Haiku publishes five M06 entries for `sklearn/utils/_array_api.py`. Its M11 query asks about tree and ensemble files. None of those files has a published entry at query time.

Pending capture does not count as published history. Luna ends M06 with 30 pending entries and zero published entries. Haiku ends M06 with five published entries and 19 pending entries.

The service reads the store again for each call. It can serve entries from the current stage after publication. A portable test verifies this behavior.

A separate canary uses an implementation file from sklearn in a temporary workspace. It publishes five entries through the store API. It then discards the publication objects and creates a fresh service. A query for that file returns all five entries.

The canary has no model calls, conversation history, or hidden test inputs. Its author text is synthetic. It proves lookup works; it does not prove a model benefit.

New telemetry records the number of published entries, their IDs, their files, normalized query paths, direct matches, and served IDs. An explicit reason describes an empty result. Model-facing text, selection rules, and budgets stay unchanged.

The second-stage queries do not test whether either model can use the earlier history for the array API. The next real pilot must let each model choose its own queries. This audit does not force recall or add unrelated intent text.

The report in JSON has each query time, source hashes, store coverage, publication counts, and the reason for the empty result.
