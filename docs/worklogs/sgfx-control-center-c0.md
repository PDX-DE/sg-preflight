# SGFX QA Control Center C0 Worklog

| Date | Start | End | Elapsed | Work package | Verified result | Commit |
|---|---:|---:|---:|---|---|---|
| 2026-07-12 | 2026-07-12 22:27:50 +02:00 | 2026-07-12 22:58:42 +02:00 | 00:30:52 | C0 RED-first implementation plan | Twelve-task plan checked for sequencing, fences, markers, and staged diff integrity | `89c7980` |
| 2026-07-12 | 2026-07-12 22:58:42 +02:00 | 2026-07-12 23:33:22 +02:00 | 00:34:40 | Task 1 explicit profile selection | Neutral startup and explicit valid profile behavior passed focused and compatibility gates | `f38f0c7` |
| 2026-07-12 | 2026-07-12 23:33:22 +02:00 | 2026-07-12 23:41:38 +02:00 | 00:08:16 | Task 2 isolated local preflight | Exact four-pack action and run-profile acceptance gates passed | `07ac1e9` |
| 2026-07-12 | 2026-07-12 23:41:38 +02:00 | 2026-07-12 23:50:52 +02:00 | 00:09:14 | Task 3 audited Home action | Fail-closed Home capability and action-isolation gates passed | `0ce1a5a` |
| 2026-07-12 | 2026-07-12 23:50:52 +02:00 | 2026-07-13 00:01:29 +02:00 | 00:10:37 | Task 4 QA truth reducer | Reducer, bounded shell composition, and read-safety gates passed | `6bac436` |
| 2026-07-13 | 2026-07-13 00:01:29 +02:00 | 2026-07-13 00:22:28 +02:00 | 00:20:59 | Task 5 Control Center Home | Host, QML, capability, parser, and rendered viewport review passed | `7bf5240` |
| 2026-07-13 | 2026-07-13 00:22:28 +02:00 | 2026-07-13 00:38:26 +02:00 | 00:15:58 | Task 6 Full QA gate alignment | Full QA, presenter, headless QML, and evidence-safety gates passed | `2ee87a6` |
| 2026-07-13 | 2026-07-13 00:38:26 +02:00 | 2026-07-13 00:52:02 +02:00 | 00:13:36 | Task 7 same-data Presentation | Host, inspection, core, QML, parser, and committed checks passed | `a1625e7` |
| 2026-07-13 | 2026-07-13 00:52:02 +02:00 | 2026-07-13 01:19:28 +02:00 | 00:27:26 | Task 8 bounded preview channel | Preview, core, capability, host, cache, and lifecycle gates passed | `d63d044` |
| 2026-07-13 | 2026-07-13 01:19:28 +02:00 | 2026-07-13 01:49:54 +02:00 | 00:30:26 | Task 9 Ramses preview helper | Native contract, finite real-scene render, manifest, source hash, and provider round trip passed | `ff7bdb9` |
| 2026-07-13 | 2026-07-13 01:49:54 +02:00 | 2026-07-13 02:05:50 +02:00 | 00:15:56 | Task 10 interaction and provenance | Fonts, finite motion, accessibility, viewports, package inputs, and regressions passed | `1e76769` |

Task 11 recovery, selected-profile correction, and Task 12 delivery work are not assigned duration rows because the frozen-session windows do not have both durable start and end timestamps. No idle or unrecorded time is inferred.
