import base64
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, UUID, uuid5

NO_EPISODE_RUN_NAMESPACE = uuid5(NAMESPACE_URL, "silverstream/leaderboard/no-episode-run")


def derive_run_id(tracker_id: UUID, trace_id: UUID) -> UUID:
    return uuid5(NO_EPISODE_RUN_NAMESPACE, f"{tracker_id}:{trace_id.hex}")


def build_deep_dive_url(collector_base_url: str, tracker_id: UUID, trace_id: UUID) -> str:
    run_id = derive_run_id(tracker_id, trace_id)
    trace_id_b64 = base64.b64encode(bytes.fromhex(trace_id.hex)).decode()
    params = urlencode({"tracker": str(tracker_id), "traceIdB64": trace_id_b64})
    return f"{collector_base_url}/deep-dive/run/{run_id}?{params}"
