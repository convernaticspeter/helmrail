from pathlib import Path

from scripts.run_canaries import DEFAULT_CANARIES, load_canaries


def test_internal_pilot_canaries_are_valid():
    canaries = load_canaries(Path(DEFAULT_CANARIES))
    assert len(canaries) == 20
    ids = [item["id"] for item in canaries]
    assert len(ids) == len(set(ids))
    assert all(item.get("prompt") for item in canaries)
    assert all(item.get("model") for item in canaries)
