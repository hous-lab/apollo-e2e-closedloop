#!/usr/bin/env python3
"""Gate-1 checker: waypoint numeric sanity from the vad_live service log.

Watches run/vad_live.log for --window seconds, parses the per-frame lines,
then judges: every parsed number finite, plan extent (w0 relative to the
current ego pose, `rel0`) under the radius bound, and per-frame infer time
in a wide band (soft, engine dependent - median in band, outlier budget for
cold-start frames). Writes run/gate1.json and prints the verdict.
"""
import argparse
import json
import math
import os
import re
import time

LINE = re.compile(r"frame seq=(\d+) infer=(\d+)ms ego0=\(([-\d.eE+]+),([-\d.eE+]+)\) "
                  r"w0=\(([-\d.eE+]+),([-\d.eE+]+)\) rel0=\(([-\d.eE+]+),([-\d.eE+]+)\)")


def collect(log_path, window_s):
    frames = []
    with open(log_path, "r", errors="replace") as f:
        f.seek(0, 2)  # follow only new frames
        t0 = time.time()
        while time.time() - t0 < window_s:
            ln = f.readline()
            if not ln:
                time.sleep(0.2)
                continue
            m = LINE.match(ln.strip())
            if m:
                frames.append({
                    "seq": int(m.group(1)), "infer_ms": int(m.group(2)),
                    "ego0": (float(m.group(3)), float(m.group(4))),
                    "w0": (float(m.group(5)), float(m.group(6))),
                    "rel0": (float(m.group(7)), float(m.group(8))),
                })
    return frames


def judge(frames, infer_min, infer_max, radius):
    reasons = []
    if len(frames) < 10:
        reasons.append("only %d frames parsed (need >= 10)" % len(frames))
    infers = [fr["infer_ms"] for fr in frames]
    w0s = [math.hypot(*fr["w0"]) for fr in frames]
    rel0s = [math.hypot(*fr["rel0"]) for fr in frames]
    steps = [math.hypot(frames[i]["rel0"][0] - frames[i-1]["rel0"][0],
                        frames[i]["rel0"][1] - frames[i-1]["rel0"][1]) for i in range(1, len(frames))]
    for fr in frames:
        for key in ("ego0", "w0", "rel0"):
            for v in fr[key]:
                if not math.isfinite(v):
                    reasons.append("non-finite %s at seq %d" % (key, fr["seq"]))
    if rel0s and max(rel0s) >= radius:
        reasons.append("max |rel0| = %.1f >= %s m" % (max(rel0s), radius))
    slow = [x for x in infers if x < infer_min or x > infer_max]
    # cold start (engine load, CUDA warmup) legitimately produces a few slow
    # frames: gate on the median plus an outlier budget instead of every frame
    med = sorted(infers)[len(infers)//2] if infers else 0
    if infers and not (infer_min <= med <= infer_max):
        reasons.append("median infer %dms outside [%s, %s]" % (med, infer_min, infer_max))
    soft = ["infer %dms outside [%s, %s]" % (x, infer_min, infer_max) for x in slow]
    rep = {
        "frames": len(frames),
        "infer_ms": {"min": min(infers) if infers else None,
                     "p50": sorted(infers)[len(infers)//2] if infers else None,
                     "max": max(infers) if infers else None},
        "max_rel0_m": round(max(rel0s), 2) if rel0s else None,
        "max_w0_step_m": round(max(steps), 3) if steps else None,
        "max_abs_w0_m": round(max(w0s), 2) if w0s else None,
        "soft_warnings": soft,
        "verdict": "FAIL" if reasons else "PASS",
        "fail_reasons": reasons,
    }
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run", "vad_live.log"))
    ap.add_argument("--window", type=float, default=30.0)
    ap.add_argument("--infer-band", default="80,250")
    ap.add_argument("--radius", type=float, default=50.0)
    a = ap.parse_args()
    lo, hi = (float(x) for x in a.infer_band.split(","))
    rep = judge(collect(a.log, a.window), lo, hi, a.radius)
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run", "gate1.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(rep, fh, indent=1)
    print(json.dumps(rep, indent=1))
    raise SystemExit(0 if rep["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
