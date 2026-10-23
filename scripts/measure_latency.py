#!/usr/bin/env python3
"""Summarize the VAD live-service latency log into gate-3 evidence.

Reads run/vad_latency.csv (seq,infer_ms rows written by vad_live_service.py),
computes count / mean / p50 / p90 / p99 / max and the implied plan rate
(1000 / p50), writes run/latency_summary.json and prints it.
Optional: pass --dmon-log (nvidia-smi dmon output) to attach GPU stats.
"""
import argparse
import csv
import json
import os
import re


def percentile(sorted_vals, q):
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, int(round((len(sorted_vals) - 1) * q))))
    return sorted_vals[k]


def parse_dmon(path):
    """Extract mean SM + mem util % from an nvidia-smi dmon log (-o TD: date time gpu sm mem ...)."""
    sms, mems = [], []
    with open(path, errors="replace") as f:
        for ln in f:
            if ln.startswith("#"):
                continue
            fields = ln.split()
            if len(fields) >= 5 and fields[0].isdigit():
                sms.append(int(fields[3]))   # sm %
                mems.append(int(fields[4]))  # mem %
    if not sms:
        return None
    if not sms:
        return None
    return {"sm_util_mean_pct": round(sum(sms) / len(sms), 1),
            "mem_util_mean_pct": round(sum(mems) / len(mems), 1),
            "samples": len(sms)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv",
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run", "vad_latency.csv"))
    ap.add_argument("--dmon-log", default=None)
    ap.add_argument("--out",
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run", "latency_summary.json"))
    a = ap.parse_args()
    vals = []
    with open(a.csv, newline="") as f:
        for row in csv.DictReader(f):
            try:
                vals.append(float(row["infer_ms"]))
            except (KeyError, ValueError):
                continue
    vals.sort()
    if not vals:
        raise SystemExit("no latency rows parsed from %s" % a.csv)
    p50 = percentile(vals, 0.50)
    rep = {
        "source": a.csv,
        "n": len(vals),
        "mean_ms": round(sum(vals) / len(vals), 1),
        "p50_ms": round(p50, 1),
        "p90_ms": round(percentile(vals, 0.90), 1),
        "p99_ms": round(percentile(vals, 0.99), 1),
        "max_ms": round(vals[-1], 1),
        "plan_hz_at_p50": round(1000.0 / p50, 2) if p50 else None,
    }
    if a.dmon_log and os.path.isfile(a.dmon_log):
        rep["gpu_dmon"] = parse_dmon(a.dmon_log)
    with open(a.out, "w") as f:
        json.dump(rep, f, indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
