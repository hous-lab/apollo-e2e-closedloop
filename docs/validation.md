# Validation: staged gates and evidence layout

The pipeline uses three sequential gates instead of one big-bang check. Each gate has numeric criteria, writes its verdict to run/, and every gate is rerunnable alone via --from-stage.

## Gate table

| gate | stage | criteria | evidence |
|---|---|---|---|
| 1 waypoint sanity | 5 | frames >= 10 in GATE1_WINDOW; all parsed numbers finite; every waypoint within 50 m of ego; infer inside a per-model soft band (VAD 80-250 ms, SparseDriveV2 20-200 ms; warnings only) | run/gate1.json |
| 2 closed-loop drive | 7 | net displacement > 5 m, max speed >= 0.3 m/s, watchdog restarts <= budget (default 3 per 10 min) | run/gate2.json (plus run/gate2_drive.json) |
| 3 latency table | 8 | summary produced; numbers land in the [README](../README.md) with device and driver noted | run/latency_summary.json + run/gpu_dmon.log |

For reference, the earlier GPU-server closed-loop runs drove about 130 m under real throttle at sustained 0.33-0.66 m/s. The laptop gate 2 thresholds are set so that a passing laptop run demonstrates the same behavior class, not the same number.

Measured example, single laptop run (RTX 4090 Laptop GPU), VAD: gate 1 PASS with 195 frames in 30 s, max plan extent (rel0) 2.82 m, infer p50 130 ms; gate 2 PASS with net displacement 8.6 m at max speed 3.1 m/s and zero watchdog restarts; gate 3 over n=18061 frames, p50 192 ms / p99 376 ms, 5.2 Hz plan rate at p50, mean GPU SM util 34.9% in the 60 s sampling window. In the same session under MODEL=sparsedrive: gate 1 PASS with 802 frames in 60 s, rel0 <= 3.05 m, p50 70 ms; gate 2 PASS at 7.3 m / 4.2 m/s, zero restarts; gate 3 over n=5649 frames, p50 74.9 ms / p99 130 ms, 13.35 Hz at p50, SM util 34.1%. The sim clock runs at ~0.115x real time at these settings (2.3 Hz tick x 0.05 s fixed delta), so a 300 s wall-clock window covers about 35 sim-seconds of driving.

## Evidence layout

After a full bring-up, run/ holds the whole audit trail:

| file | from stage | content |
|---|---|---|
| run/stageN_*.log | 0-8 | one log per stage, including the stage-4 probe counts |
| run/carla.log | 3 | CARLA server stdout |
| run/vad_live.log | 5 | per-frame model lines (seq, infer ms, ego0, w0) |
| run/vad_latency.csv | 5-8 | per-frame infer_ms rows |
| run/sparsedrive_live.log | 5 | per-frame model lines, MODEL=sparsedrive (same line format) |
| run/sparsedrive_latency.csv | 5-8 | per-frame infer_ms rows, MODEL=sparsedrive |
| run/gate1.json | 5 | gate 1 verdict |
| run/gate2.json | 7 | gate 2 verdict (displacement, max speed, restarts vs budget) |
| run/gate2_drive.json | 7 | raw drive JSON: pose/chassis/control counts and speed stats |
| run/watchdog.log + watchdog_restarts.log | 7 | self-heal activity and restart timestamps |
| run/gpu_dmon.log | 8 | nvidia-smi dmon samples (util + mem) |
| run/latency_summary.json | 8 | gate 3: n / mean / p50 / p90 / p99 / max + plan Hz at p50 |

All of run/ is gitignored: it is machine evidence, not repo content. The README result table quotes the summary numbers and names the device.
