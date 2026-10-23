# models/vad

VAD end-to-end planner integration for the apollo-e2e-closedloop pipeline.

The VAD-specific runtime is `scripts/vad_live_service.py`; this directory
documents the model-facing configuration. Everything else in the pipeline
(CARLA, Apollo container, bridge, relay, control, watchdog) is model-agnostic
and shared - swapping in another end-to-end model only means adding a
`models/<name>/` directory and a host-side service that speaks the same
relay TCP contract (see `docs/model_contract.md`).

## Artifacts

See [../../ckpts/README.md](../../ckpts/README.md): engines and the plugin
library come from the [hous-lab/vad-trt-edge](https://github.com/hous-lab/vad-trt-edge)
x86 pipeline. Defaults: `VAD_BB_ENGINE=backbone_int8.engine`,
`VAD_HD_ENGINE=head_withprev_fp16_fixed_v2.engine`.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `VAD_ENGINES_DIR` | (required) | directory with the two engines |
| `VAD_PLUGIN` | (required) | path to `libplugins.so` |
| `VAD_BB_ENGINE` | `backbone_int8.engine` | backbone engine file |
| `VAD_HD_ENGINE` | `head_withprev_fp16_fixed_v2.engine` | head engine file |
| `VAD_CAM_FALLBACK` | empty | `replicate` fills missing surround views with the front image (debug) |
| `CONDA_ENV` | `p1bevrc` | host conda env with tensorrt + torch |

## Known simplifications

- static camera extrinsics approximated by identity + 2 m forward shift,
  zero can_bus/shift, persistent zero prev-bev, command index fixed to 0 -
  see `docs/model_contract.md` for the full list and the map to ADCTrajectory.
