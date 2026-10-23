# models/sparsedrive (reserved - next phase)

Placeholder for the SparseDrive end-to-end model integration.

The plan: reuse this pipeline unchanged - the relay (`scripts/relay_cyber_tcp.py`)
and every orchestration script are model-agnostic. SparseDrive only adds:

1. a host-side `sd_live_service.py` speaking the same TCP contract
   (obs in / waypoints out, see `docs/model_contract.md`),
2. `models/sparsedrive/` engine configuration pointing at the
   [hous-lab/sparsedrive-trt-edge](https://github.com/hous-lab/sparsedrive-trt-edge)
   deployment artifacts,
3. a `start_vad.sh` equivalent (`start_sparsedrive.sh`).

No engines are promised yet; this file ships as the integration checklist.
