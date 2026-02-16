# Oracle Creator: Self-Extending Verification

**Status**: Design phase
**Date**: 2026-02-14

---

## 1. The Problem

The oracle system today only supports `pytest`. The `OracleType` enum has one value. To support a new domain (Android UI, RTL testbenches, iOS, ROS2, browser e2e), someone has to manually build the Docker setup, write the agent prompt, wire the execution — for each domain.

This doesn't scale. There are hundreds of verification domains. New frameworks appear constantly (Jetpack Compose testing, SwiftUI testing, Bun test runner). You can't pre-build them all.

---

## 2. The Solution: Oracle Creator Agent

An agent that **creates new oracle types on demand**. When a user needs an oracle type that doesn't exist, they launch the oracle creator. It understands the target domain, builds the configuration, validates it, and registers it for future use.

```
Today:
  User has a rule → oracle type exists? → YES → generate + run
                                        → NO  → not supported

With oracle creator:
  User has a rule → oracle type exists? → YES → generate + run
                                        → NO  → launch oracle creator agent
                                                 → agent builds the oracle type config
                                                 → self-validates (builds image, runs hello-world)
                                                 → registers the new oracle type
                                                 → generate + run
```

The oracle system becomes **self-extending**. Users are never blocked by missing oracle types.

---

## 3. What an Oracle Type Config Is

An oracle type is a configuration struct that tells the oracle system how to generate and run verification artifacts for a specific domain:

```python
@dataclass
class OracleTypeConfig:
    # Identity
    name: str                     # "android_ui_test"
    description: str              # "Espresso UI tests for Android apps"

    # Docker environment
    base_image: str               # "cimg/android:2024.01"
    install_commands: list[str]   # ["sdkmanager ...", "pip install ..."]

    # Execution
    run_command: str              # "gradle connectedAndroidTest"
    pass_pattern: str             # Regex to detect pass in output
    fail_pattern: str             # Regex to detect failure in output

    # Oracle agent instructions
    agent_prompt: str             # System prompt for the oracle-generating agent
                                  # "Write an Espresso test that verifies..."

    # File conventions
    artifact_extension: str       # ".kt", ".py", ".sv", ".js"
    artifact_template: str        # Optional boilerplate the agent starts from

    # Metadata
    created_by: str               # "oracle_creator" | "built_in"
    validated: bool               # Whether self-validation passed
    validation_log: str           # Output from validation run
```

This is the entire plugin. Everything else (Docker isolation, concurrency, result collection) is handled by the existing `runner.py`.

---

## 4. Where Oracle Type Configs Live

```
.kekule/
  oracle_types/
    pytest.json              # Built-in, ships with Kekule
    cocotb.json              # Built-in
    playwright.json          # Built-in
    android_ui_test.json     # Created by oracle creator agent
    ios_xctest.json          # Created by oracle creator agent
    verilog_iverilog.json    # Created by oracle creator agent
    ros2_integration.json    # Created by oracle creator agent
    ...
```

The oracle system loads all configs from this directory at runtime. New JSON file = new oracle type available immediately.

---

## 5. How the Oracle Creator Agent Works

### Input

User describes the verification domain in natural language:

```
"I need an oracle for Android UI testing using Espresso.
 My project uses Jetpack Compose and Kotlin."
```

### Agent Workflow

```
Step 1: UNDERSTAND THE DOMAIN
  - What testing framework exists? (Espresso, UI Automator, Compose Testing)
  - What language are tests written in? (Kotlin, Java)
  - What's the execution environment? (Android SDK, Gradle, emulator or Robolectric)
  - What does pass/fail look like in output?

Step 2: DETERMINE DOCKER SETUP
  - Base image: cimg/android:2024.01 or custom
  - Install commands: SDK components, Gradle, Robolectric
  - Can it run without hardware? (Robolectric = yes, emulator = needs KVM)

Step 3: WRITE THE AGENT PROMPT
  System prompt for future oracle-generating agents:
  "Write an Espresso test in Kotlin that verifies the rule.
   Use @RunWith(AndroidJUnit4::class).
   Use onView(withId(R.id.xxx)).check(matches(isDisplayed())).
   Use Robolectric for unit-level UI tests (no emulator needed).
   File should be a standalone test class in the androidTest source set."

Step 4: DETERMINE EXECUTION
  - Run command: ./gradlew testDebugUnitTest
  - Pass pattern: "BUILD SUCCESSFUL" or "(\d+) tests? passed"
  - Fail pattern: "BUILD FAILED" or "(\d+) tests? failed"

Step 5: SELF-VALIDATE
  - Build the Docker image (does it build?)
  - Write a trivial hello-world test for the domain
  - Run the test in the container (does it execute?)
  - Check pass/fail detection (does the regex match?)

  All pass? → Save config as .kekule/oracle_types/<name>.json
  Fail?     → Debug, adjust config, retry
```

### Output

A validated `OracleTypeConfig` saved as JSON, ready for immediate use.

---

## 6. Examples

### Example: Android UI (Espresso + Robolectric)

```json
{
  "name": "android_espresso",
  "description": "Espresso UI tests for Android apps, runs via Robolectric (no emulator)",
  "base_image": "cimg/android:2024.01",
  "install_commands": [
    "sdkmanager --install 'platforms;android-34'",
    "sdkmanager --install 'build-tools;34.0.0'"
  ],
  "run_command": "./gradlew testDebugUnitTest --tests oracle_tests.*",
  "pass_pattern": "BUILD SUCCESSFUL",
  "fail_pattern": "BUILD FAILED|FAILURES",
  "agent_prompt": "Write an Espresso UI test in Kotlin that verifies the rule.\nUse @RunWith(AndroidJUnit4::class) with Robolectric.\nUse onView(withId(...)).check(matches(...)) for view assertions.\nUse ActivityScenario.launch() to start activities.\nFile should be a standalone Kotlin test class.\nDo NOT require a running emulator.",
  "artifact_extension": ".kt",
  "artifact_template": "",
  "created_by": "oracle_creator",
  "validated": true,
  "validation_log": "Docker build: OK (47s)\nHello-world test: PASS\nPass pattern matched: yes"
}
```

### Example: RTL Testbench (cocotb)

```json
{
  "name": "cocotb_rtl",
  "description": "cocotb testbenches for RTL verification (Verilog/SystemVerilog via Icarus Verilog)",
  "base_image": "python:3.11-slim",
  "install_commands": [
    "apt-get update && apt-get install -y iverilog",
    "pip install cocotb"
  ],
  "run_command": "make -f Makefile.oracle SIM=icarus",
  "pass_pattern": "passed",
  "fail_pattern": "failed|ERROR",
  "agent_prompt": "Write a cocotb testbench in Python that verifies the rule.\nUse @cocotb.test() decorator for test functions.\nDrive inputs with dut.<signal>.value = X.\nCheck outputs with assert dut.<signal>.value == expected.\nUse cocotb.clock.Clock for clocked designs.\nUse await RisingEdge(dut.clk) for synchronization.\nAlso generate a Makefile.oracle with TOPLEVEL, MODULE, and SIM variables.\nThe Makefile should include $(shell cocotb-config --makefiles)/Makefile.sim.",
  "artifact_extension": ".py",
  "artifact_template": "",
  "created_by": "oracle_creator",
  "validated": true,
  "validation_log": "Docker build: OK (23s)\nHello-world test: PASS (half-adder)\nPass pattern matched: yes"
}
```

### Example: Raw Verilog (Icarus Verilog)

```json
{
  "name": "iverilog_rtl",
  "description": "SystemVerilog/Verilog testbenches compiled and simulated with Icarus Verilog",
  "base_image": "hdlc/sim:latest",
  "install_commands": [],
  "run_command": "iverilog -g2012 -o sim oracle_tests/*.sv dut/*.sv && ./sim",
  "pass_pattern": "TEST PASSED|All tests passed",
  "fail_pattern": "TEST FAILED|ASSERTION FAILED|ERROR",
  "agent_prompt": "Write a SystemVerilog testbench that verifies the rule.\nInstantiate the DUT (device under test) in the testbench module.\nDrive stimulus via initial blocks.\nCheck outputs with assert() or if/else + $error().\nPrint 'TEST PASSED' on success, 'TEST FAILED' on failure.\nCall $finish at the end.\nUse `timescale 1ns/1ps at the top.\nFile extension must be .sv.",
  "artifact_extension": ".sv",
  "artifact_template": "",
  "created_by": "oracle_creator",
  "validated": true,
  "validation_log": "Docker build: OK (8s)\nHello-world test: PASS (and-gate)\nPass pattern matched: yes"
}
```

### Example: Playwright (Browser E2E)

```json
{
  "name": "playwright_e2e",
  "description": "Playwright end-to-end browser tests for web applications",
  "base_image": "mcr.microsoft.com/playwright:v1.42.1-jammy",
  "install_commands": [
    "npm install @playwright/test",
    "npx playwright install chromium"
  ],
  "run_command": "npx playwright test oracle_tests/ --reporter=line",
  "pass_pattern": "\\d+ passed",
  "fail_pattern": "\\d+ failed|Error:",
  "agent_prompt": "Write a Playwright end-to-end test in TypeScript that verifies the rule.\nUse import { test, expect } from '@playwright/test'.\nUse page.goto(), page.locator(), expect(locator).toBeVisible(), etc.\nTests should be self-contained and not depend on external state.\nAssume the app is running at http://localhost:3000 unless oracle_config specifies otherwise.\nFile extension must be .spec.ts.",
  "artifact_extension": ".spec.ts",
  "artifact_template": "",
  "created_by": "oracle_creator",
  "validated": true,
  "validation_log": "Docker build: OK (92s)\nHello-world test: PASS (page title check)\nPass pattern matched: yes"
}
```

---

## 7. Self-Validation Protocol

The oracle creator MUST validate its output before registering. This prevents broken configs from entering the system.

```
Validation steps:

1. BUILD IMAGE
   docker build -t oracle-validate-<name> .
   Expected: exit code 0
   On failure: agent reads build log, fixes Dockerfile, retries

2. WRITE HELLO-WORLD TEST
   Agent writes a minimal test for the domain:
   - pytest: def test_true(): assert True
   - cocotb: half-adder test
   - Espresso: check activity launches
   - Playwright: check page.title() exists
   - iverilog: AND gate testbench

3. RUN HELLO-WORLD
   docker run --rm oracle-validate-<name>
   Expected: exit code 0, output matches pass_pattern

4. VERIFY PASS/FAIL DETECTION
   Intentionally break the hello-world test
   Run again
   Expected: exit code != 0, output matches fail_pattern

5. RECORD RESULTS
   Save validation log to config
   Set validated: true only if all steps pass
```

If validation fails, the agent has up to 3 retries to debug and fix the config. Common failure modes:

- Missing system dependency → add to `install_commands`
- Wrong base image → switch image
- Incorrect run command → adjust path/flags
- Pass/fail regex doesn't match output format → fix regex

---

## 8. Integration with Existing Oracle System

### How runner.py changes

Currently `_generate_dockerfile()` and the runner hardcode pytest. With oracle types:

```python
def _generate_dockerfile(oracle_type_config: OracleTypeConfig, repo_path: Path) -> str:
    install_lines = "\n".join(
        f"RUN {cmd}" for cmd in oracle_type_config.install_commands
    )
    return f"""FROM {oracle_type_config.base_image}
WORKDIR /workspace
COPY repo/ /workspace/
{install_lines}
COPY oracle_tests/ /workspace/oracle_tests/
CMD {oracle_type_config.run_command}
"""
```

### How agent.py changes

Currently the agent prompt says "write a pytest test." With oracle types:

```python
def _build_oracle_prompt(rule: Rule, test_file: Path, oracle_type_config: OracleTypeConfig) -> str:
    return f"""## Rule to Verify
**Rule ID:** {rule.id}
**Description:** {rule.description}

## Instructions
{oracle_type_config.agent_prompt}

Write the verification artifact to: {test_file}
"""
```

### How schemas.py changes

```python
class OracleType(str, Enum):
    PYTEST = "pytest"
    # Static enum is replaced by dynamic lookup:
    # OracleType is now just a string that maps to a config file
    # in .kekule/oracle_types/<name>.json

# Or: keep the enum for built-ins, allow custom strings for creator-made types
```

### Loading oracle types at runtime

```python
def load_oracle_type(name: str) -> OracleTypeConfig:
    # Check built-in types first
    builtin_path = PACKAGE_DIR / "oracle_types" / f"{name}.json"
    if builtin_path.exists():
        return OracleTypeConfig(**json.loads(builtin_path.read_text()))

    # Check user-created types
    custom_path = Path(".kekule/oracle_types") / f"{name}.json"
    if custom_path.exists():
        return OracleTypeConfig(**json.loads(custom_path.read_text()))

    raise ValueError(
        f"Oracle type '{name}' not found. "
        f"Use the oracle creator to build it: "
        f"python -m kekule.oracle create --type '{name}'"
    )
```

---

## 9. Three-Layer Architecture

The oracle system has three layers, each independent:

```
Layer 3: ORACLE CREATOR
         Creates new oracle types on demand
         Input: user description of verification domain
         Output: OracleTypeConfig (validated JSON)
         │
         ▼
Layer 2: ORACLE GENERATOR (agent.py — exists today)
         Uses oracle type configs to write test artifacts
         Input: Rule + OracleTypeConfig + repo context
         Output: test file / script / testbench
         │
         ▼
Layer 1: ORACLE RUNNER (runner.py — exists today)
         Executes artifacts in Docker, returns pass/fail
         Input: artifact + OracleTypeConfig + repo
         Output: OracleResult (passed, evidence, exit_code)
```

Layer 1 and Layer 2 exist and work for pytest. Layer 3 is new. Adding Layer 3 makes Layers 1 and 2 domain-agnostic — they just read from the config.

---

## 10. Dashboard UX

In the dashboard, oracle type selection becomes:

```
┌─────────────────────────────────────┐
│  Select Oracle Type for Rule        │
│                                     │
│  ● pytest            (built-in)     │
│  ○ playwright_e2e    (built-in)     │
│  ○ cocotb_rtl        (built-in)     │
│  ○ android_espresso  (custom)  ✓    │
│  ○ iverilog_rtl      (custom)  ✓    │
│                                     │
│  [+ Create New Oracle Type]         │
│                                     │
└─────────────────────────────────────┘

✓ = validated by oracle creator
```

Clicking **"Create New Oracle Type"** opens a conversation with the oracle creator agent. User describes the domain. Agent produces and validates the config. It appears in the list immediately.

---

## 11. Limitations and Edge Cases

### Domains that can't run in Docker

Some verification domains need specific hardware or OS:

| Domain | Problem | Workaround |
|---|---|---|
| iOS XCTest | Requires macOS + Xcode | SSH runner to a Mac (not Docker) |
| FPGA-in-the-loop | Requires physical FPGA | Remote runner with FPGA attached |
| GPU compute (CUDA) | Requires NVIDIA GPU | Docker with `--gpus` flag |
| Mobile emulator | Requires KVM / nested virtualization | Docker with `--privileged` or cloud emulator API |

The oracle runner should eventually support non-Docker backends (SSH, cloud API, etc.). But Docker covers the majority of cases. The `OracleTypeConfig` could be extended with a `runner_type` field:

```python
runner_type: str  # "docker" | "ssh" | "cloud" | "local"
runner_config: dict  # Runner-specific config (SSH host, cloud API endpoint, etc.)
```

### Large Docker images

Some domains have heavy base images (Android SDK: 2+ GB, CUDA: 4+ GB). Mitigations:

- Cache base images locally (don't re-pull every run)
- Use slim variants where possible
- The oracle creator agent should prefer lightweight options (Robolectric over emulator, CPU-only PyTorch over CUDA)

### Oracle creator failure modes

- Agent doesn't know the domain well enough → produces bad config → self-validation catches it
- Base image doesn't exist → Docker build fails → agent picks a different image
- Framework requires licensing (Synopsys VCS, Cadence Xcelium) → agent should detect this and warn the user
- Framework is too new for the LLM's training data → web search for docs, or user provides documentation link
