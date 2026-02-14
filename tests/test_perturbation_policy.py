from kekule.benchmarks.perturbation_policy import (
    PerturbationPolicy,
    evaluate_post_tool_use_perturbation,
)


def _long_pytest_output() -> str:
    body = "\n".join([f"line {i}" for i in range(220)])
    return (
        "Traceback (most recent call last):\n"
        "  File \"test_example.py\", line 10, in test_x\n"
        "AssertionError: boom\n"
        f"{body}\n"
        "FAILED test_example.py::test_x - AssertionError: boom\n"
    )


def test_tool_io_perturbation_fires_for_verification_command():
    policy = PerturbationPolicy(
        mode="tool_io_degrade",
        intensity=1.0,
        target_tools=("Bash",),
        seed=7,
        phase_scope="swarm_phase1",
    )

    result = evaluate_post_tool_use_perturbation(
        policy=policy,
        phase_tag="swarm_phase1",
        tool_name="Bash",
        tool_input={"command": "pytest -q"},
        tool_response=_long_pytest_output(),
        tool_use_id="toolu_1",
    )

    assert result.eligible is True
    assert result.fired is True
    assert result.updated_tool_output is not None
    assert result.event["output_hash_before"] != result.event["output_hash_after"]
    assert "truncated by perturbation policy" in str(result.updated_tool_output) or "omitted by perturbation policy" in str(result.updated_tool_output)


def test_non_verification_bash_command_is_not_eligible():
    policy = PerturbationPolicy(
        mode="tool_io_degrade",
        intensity=1.0,
        target_tools=("Bash",),
        seed=7,
        phase_scope="swarm_phase1",
    )

    result = evaluate_post_tool_use_perturbation(
        policy=policy,
        phase_tag="swarm_phase1",
        tool_name="Bash",
        tool_input={"command": "ls -la"},
        tool_response=_long_pytest_output(),
        tool_use_id="toolu_2",
    )

    assert result.eligible is False
    assert result.fired is False
    assert result.reason == "bash_command_not_verification"


def test_phase_scope_blocks_outside_swarm_phase():
    policy = PerturbationPolicy(
        mode="tool_io_degrade",
        intensity=1.0,
        target_tools=("Bash",),
        seed=11,
        phase_scope="swarm_phase1",
    )

    result = evaluate_post_tool_use_perturbation(
        policy=policy,
        phase_tag="single_agent",
        tool_name="Bash",
        tool_input={"command": "pytest -q"},
        tool_response="ok",
        tool_use_id="toolu_3",
    )

    assert result.eligible is False
    assert result.fired is False
    assert result.reason == "phase_not_allowed"


def test_decision_is_deterministic_for_same_input():
    policy = PerturbationPolicy(
        mode="tool_io_degrade",
        intensity=0.37,
        target_tools=("Bash",),
        seed=17,
        phase_scope="swarm_phase1",
    )
    kwargs = dict(
        policy=policy,
        phase_tag="swarm_phase1",
        tool_name="Bash",
        tool_input={"command": "pytest -k test_case"},
        tool_response="short output",
        tool_use_id="toolu_4",
    )

    first = evaluate_post_tool_use_perturbation(**kwargs)
    second = evaluate_post_tool_use_perturbation(**kwargs)

    assert first.fired == second.fired
    assert first.reason == second.reason
    assert first.event.get("roll") == second.event.get("roll")


def test_dict_output_transform_preserves_structure():
    policy = PerturbationPolicy(
        mode="tool_io_degrade",
        intensity=1.0,
        target_tools=("Bash",),
        seed=23,
        phase_scope="swarm_phase1",
    )
    tool_response = {
        "stdout": _long_pytest_output(),
        "stderr": "",
        "exit_code": 1,
    }

    result = evaluate_post_tool_use_perturbation(
        policy=policy,
        phase_tag="swarm_phase1",
        tool_name="Bash",
        tool_input={"command": "python -m pytest tests/test_x.py"},
        tool_response=tool_response,
        tool_use_id="toolu_5",
    )

    assert result.fired is True
    assert isinstance(result.updated_tool_output, dict)
    assert result.updated_tool_output["exit_code"] == 1
    assert result.updated_tool_output["stdout"] != tool_response["stdout"]
