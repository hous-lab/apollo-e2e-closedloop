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

Default pair = INT8 backbone + FP16 head (best x86 config in the vad-trt-edge
README: L2(1s) 0.7828 @ 88.9 ms). The upstream VAD checkpoint (Bench2Drive
release) is download-only per the vad-trt-edge `ckpts/README.md` policy - it is
never redistributed here or on our Hugging Face.
