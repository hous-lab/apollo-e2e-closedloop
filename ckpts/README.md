# Checkpoints and engines

This repository ships no model weights and no TensorRT engines. The VAD
engines used by the closed loop are deployment artifacts of the sibling
release repo [hous-lab/vad-trt-edge](https://github.com/hous-lab/vad-trt-edge)
([Hugging Face](https://huggingface.co/hous-lab/vad-trt-edge) hosts the exported
ONNX files). Build them yourself with that repo's x86 pipeline:

```
git clone https://github.com/hous-lab/vad-trt-edge
cd vad-trt-edge
# follow its README Get Started: plugins -> ONNX -> x86 engines
# x86 products land in x86/trt_compile/output/
```

Files the closed loop consumes (TensorRT 10.x, x86_64, sm_89 tested):

| File | Role |
|---|---|
| `backbone_int8.engine` | INT8 image backbone (default) |
| `head_withprev_fp16_fixed_v2.engine` | FP16 planning head with prev-bev input (default) |
| `head_int8_fixed.engine` | alternative INT8 head (set `VAD_HD_ENGINE`) |

The perception plugin shared library (`libplugins.so`) is also built by the
vad-trt-edge pipeline (`plugins/`).

Point the closed loop at the artifacts via environment variables:

```
export VAD_ENGINES_DIR=/path/to/vad-trt-edge/x86/trt_compile/output
export VAD_PLUGIN=/path/to/vad-trt-edge/plugins/build/libplugins.so
# optional engine overrides:
# export VAD_BB_ENGINE=backbone_int8.engine VAD_HD_ENGINE=head_int8_fixed.engine
```

## SparseDriveV2 engines

Same policy: no engines in this repo. The SparseDriveV2 artifacts come from
[hous-lab/sparsedrive-trt-edge](https://github.com/hous-lab/sparsedrive-trt-edge)
(its own ckpts/README.md carries the upstream checkpoint and anchor-file
policy). x86 fp16 cascade, TensorRT 10.x:

| File | Role |
|---|---|
| `backbone_fp16.engine` | image backbone, img [6,3,384,704] |
| `head_fp16.engine` | detection head (needs `libplugins.so`) |
| `map_fp16.engine` | map head (needs `libplugins.so`) |
| `motion_plan_fp16.engine` | motion planning (needs `libplugins.so`) |
| demo npz `anchor_embed` | deploy-side constant bank passed to the plan engine |

The plan engine's `det_anchor_embed` input is a deploy-side constant (the
`anchor_embed` key of the sparsedrive-trt-edge demo npz). Point the loop at it:

```
export SPARSEDRIVE_ENGINES_DIR=/path/to/sparsedrive-trt-edge/x86/trt_compile/fp16/output
export SPARSEDRIVE_PLUGIN=/path/to/sparsedrive-trt-edge/plugins/build/libplugins.so
export SPARSEDRIVE_ANCHOR_NPZ=/path/to/sparsedrive-trt-edge/data/demo_data/sample0.npz
```

The upstream SparseDriveV2 checkpoint and its anchor/statistics files follow the
same download-only policy (see sparsedrive-trt-edge `ckpts/README.md`); this
repo ships none of them.

Default pair = INT8 backbone + FP16 head (best x86 config in the vad-trt-edge
README: L2(1s) 0.7828 @ 88.9 ms). The upstream VAD checkpoint (Bench2Drive
release) is download-only per the vad-trt-edge `ckpts/README.md` policy - it is
never redistributed here or on our Hugging Face.
