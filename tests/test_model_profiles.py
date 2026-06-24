from app.limits import RuntimeLimits
from app.model_profiles import is_coordinator_model, limits_for_visible_model


def test_visible_model_profiles_select_standard_and_ultra_limits():
    standard = limits_for_visible_model(RuntimeLimits(), "helmrail-fugu")
    ultra = limits_for_visible_model(RuntimeLimits(), "helmrail-fugu-ultra")

    assert is_coordinator_model("helmrail-fugu") is True
    assert is_coordinator_model("helmrail-fugu-ultra") is True
    assert standard.max_provider_calls == 8
    assert standard.max_output_tokens == 16384
    assert ultra.max_provider_calls == 24
    assert ultra.max_parallel_workers == 4
    assert ultra.provider_timeout_seconds == 180
    assert ultra.max_output_tokens == 32768


def test_explicit_global_limits_win_over_visible_model_profile_defaults():
    configured = RuntimeLimits(
        max_provider_calls=3,
        max_parallel_workers=2,
        provider_timeout_seconds=19,
        max_output_tokens=65536,
    )
    ultra = limits_for_visible_model(configured, "helmrail-fugu-ultra")

    assert ultra.max_provider_calls == 3
    assert ultra.max_parallel_workers == 2
    assert ultra.provider_timeout_seconds == 19
    assert ultra.max_output_tokens == 65536
