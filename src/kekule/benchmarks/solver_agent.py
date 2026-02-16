"""
SWE Solver Agent -- uses Claude Agent SDK to solve SWE-bench tasks.

Each agent:
  1. Receives a SWE-bench task (repo, base_commit, problem_statement)
  2. Clones the repo, checks out the base commit
  3. Explores code, understands the issue, writes a fix
  4. Produces a git diff patch
"""

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    UserMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)

from .config import HarnessConfig
from .task_selector import SWETask
from .tracing import AgentTraceData, build_agent_hooks

logger = logging.getLogger(__name__)


SWE_SOLVER_SYSTEM_PROMPT = """
You are an expert software engineer solving a real GitHub issue.

## Your Workflow

### Step 1: Understand the issue
Read the problem statement carefully.

### Step 2: Explore the codebase
Find the relevant files, understand the code, and develop your fix.

### Step 3: Implement the fix
Make minimal, focused changes to fix the issue.

### Step 4: Verify — MANDATORY
After implementing your fix, you MUST run the relevant test suite to verify it works:
1. Find the test file for the module you changed (look in `tests/` for a file matching the module name)
2. Run it with: `python -m pytest <test_file> -x -q` (or the project's test runner)
3. If tests fail, read the failures, fix your code, and re-run until they pass
4. Only stop when tests pass. Do NOT assume your fix is correct without running tests.

### Step 5: Edge-Case Testing — MANDATORY
Your fix will be evaluated against HIDDEN tests you cannot see. Before finalizing:
1. **Re-read the problem statement word by word.** Extract EVERY concrete behavior it describes.
   Pay attention to phrases like "should also", "in addition", "when X is None/empty/missing".
2. **Write a small test script** (`/tmp/test_edge_cases.py`) that covers:
   - The exact scenario from the problem statement
   - The boundary/None/empty/default case (e.g., what if the argument is missing?)
   - The interaction case (e.g., does the fix still work when combined with related features?)
3. **Run your edge-case tests** and fix until they all pass.

### Step 6: Self-Review — MANDATORY
After tests pass, critically review your fix before stopping:
1. **Re-read the problem statement LINE BY LINE**. Does your fix address EVERY behavior described?
   Many issues describe multiple requirements — fixing one while missing another is a common failure.
   Ask: "If someone wrote a test for each sentence in this issue, would my fix pass all of them?"
2. **Consider deletion**. Could the bug be caused by code that SHOULDN'T EXIST? Sometimes
   the correct fix is to remove a method, condition, or override — not to add or change code.
   Ask: "What happens if this code simply wasn't here?"
3. **Fewer lines = higher confidence**. If your fix is large, ask if there's a simpler approach.
4. **If uncertain**, try at least one alternative before stopping — especially deletion.

Leave changes as unstaged modifications (no git add/commit).

## Important Rules
- The repo is already cloned at the correct commit in your working directory
- Make changes directly -- do NOT create branches or commits
- Make **minimal, focused changes** -- only fix what the issue describes
- Do NOT add tests unless the issue specifically asks for them
- Do NOT modify test files unless the issue is about a test
"""

# Optional ChatOverflow skill prompt for SWE-bench agents
CHATOVERFLOW_SWE_SKILL_PROMPT = """
## ChatOverflow Q&A Forum (Optional)

You have access to the ChatOverflow Q&A forum at `{chatoverflow_api_url}`.
You can search for relevant questions and answers, or post your discoveries.

```bash
# Search existing questions
curl -s '{chatoverflow_api_url}/questions?search=YOUR+SEARCH+TERMS' \\
  -H 'Authorization: Bearer '$CHATOVERFLOW_API_KEY | python3 -m json.tool

# Post a new question
curl -s -X POST '{chatoverflow_api_url}/questions' \\
  -H 'Authorization: Bearer '$CHATOVERFLOW_API_KEY \\
  -H 'Content-Type: application/json' \\
  -d '{{"title": "Your question", "body": "Details", "forum_id": "FORUM_ID"}}' | python3 -m json.tool

# Post an answer
curl -s -X POST '{chatoverflow_api_url}/questions/QUESTION_ID/answers' \\
  -H 'Authorization: Bearer '$CHATOVERFLOW_API_KEY \\
  -H 'Content-Type: application/json' \\
  -d '{{"body": "Your answer"}}' | python3 -m json.tool

# Vote on content
curl -s -X POST '{chatoverflow_api_url}/questions/QUESTION_ID/vote' \\
  -H 'Authorization: Bearer '$CHATOVERFLOW_API_KEY \\
  -H 'Content-Type: application/json' \\
  -d '{{"vote": "up"}}' | python3 -m json.tool
```
"""


def _force_rmtree(path: Path):
    """Remove a directory tree, fixing permissions first if needed."""
    import shutil
    import stat

    def _onerror(func, fpath, exc_info):
        """Handle permission errors during rmtree."""
        try:
            os.chmod(fpath, stat.S_IRWXU)
            func(fpath)
        except Exception:
            pass

    if path.exists():
        # Fix permissions recursively first
        subprocess.run(
            ["chmod", "-R", "u+rwx", str(path)],
            capture_output=True,
            timeout=60,
        )
        shutil.rmtree(path, onerror=_onerror)


def _clone_reference_repo(task: SWETask, cache_dir: Path) -> Path:
    """
    Clone a repo once into a shared cache directory and checkout the base commit.

    Uses shallow clone + fetch for speed. Returns the cached repo directory.
    Clones into a temp dir first, then renames atomically to avoid partial caches.
    """
    cache_key = f"{task.repo.replace('/', '_')}_{task.base_commit[:12]}"
    ref_dir = cache_dir / cache_key

    # Check if already cached -- verify HEAD matches expected commit
    if (ref_dir / ".git").exists():
        try:
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(ref_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if head.returncode == 0 and head.stdout.strip() == task.base_commit:
                logger.info(f"Reference repo already cached: {ref_dir}")
                return ref_dir
            else:
                logger.warning(
                    f"Stale cache at {ref_dir} (HEAD={head.stdout.strip()[:12]}, "
                    f"expected={task.base_commit[:12]}), re-cloning"
                )
                _force_rmtree(ref_dir)
        except Exception:
            logger.warning(f"Invalid cache at {ref_dir}, re-cloning")
            _force_rmtree(ref_dir)

    # Clone into temp dir, then rename atomically
    tmp_dir = cache_dir / f".tmp_{cache_key}"
    if tmp_dir.exists():
        _force_rmtree(tmp_dir)

    logger.info(f"Cloning reference repo {task.repo_url}...")
    subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", task.repo_url, str(tmp_dir)],
        check=True,
        capture_output=True,
        timeout=600,
    )

    # Fetch the specific commit -- try increasing depths if needed
    fetched = False
    for depth in [200, 500, 1000]:
        logger.info(
            f"Fetching base commit {task.base_commit[:12]} (depth={depth})..."
        )
        result = subprocess.run(
            ["git", "fetch", "--depth", str(depth), "origin", task.base_commit],
            cwd=str(tmp_dir),
            capture_output=True,
            timeout=600,
        )
        if result.returncode == 0:
            fetched = True
            break
        logger.warning(
            f"Fetch with depth {depth} failed: {result.stderr.decode()[:200]}"
        )

    if not fetched:
        # Last resort: unshallow the entire repo
        logger.info("Fetching full history (unshallow)...")
        subprocess.run(
            ["git", "fetch", "--unshallow"],
            cwd=str(tmp_dir),
            check=True,
            capture_output=True,
            timeout=900,
        )

    logger.info(f"Checking out base commit: {task.base_commit}")
    subprocess.run(
        ["git", "checkout", "-f", task.base_commit],
        cwd=str(tmp_dir),
        check=True,
        capture_output=True,
        timeout=300,
    )

    # Atomic rename to final location
    if ref_dir.exists():
        _force_rmtree(ref_dir)
    tmp_dir.rename(ref_dir)
    logger.info(f"Reference repo cached: {ref_dir}")

    return ref_dir


def setup_workspace(task: SWETask, workspace_dir: Path, ref_repo_dir: Path) -> Path:
    """
    Create an agent workspace by copying from the cached reference repo.

    Uses cp -r which is faster than git clone --local for large repos.
    Returns the repo directory within the workspace.
    """
    workspace_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = workspace_dir / "repo"

    if repo_dir.exists():
        # Validate the existing workspace matches the expected repo
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            remote_url = result.stdout.strip() if result.returncode == 0 else ""
            expected_repo = task.repo  # e.g. "django/django"
            if expected_repo not in remote_url:
                logger.warning(
                    f"Workspace repo mismatch: expected '{expected_repo}' "
                    f"but found '{remote_url}'. Removing stale workspace."
                )
                import shutil

                shutil.rmtree(repo_dir)
            else:
                logger.info(f"Workspace already exists: {repo_dir}")
                return repo_dir
        except Exception as e:
            logger.warning(f"Could not validate workspace, recreating: {e}")
            import shutil

            shutil.rmtree(repo_dir, ignore_errors=True)

    logger.info(f"Copying reference repo to {repo_dir}")
    subprocess.run(
        ["cp", "-r", str(ref_repo_dir), str(repo_dir)],
        check=True,
        capture_output=True,
        timeout=300,
    )

    return repo_dir


def extract_patch(repo_dir: Path) -> str:
    """Extract the git diff from a repo directory as the model patch."""
    result = subprocess.run(
        ["git", "diff"],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
    )
    return result.stdout


def build_swe_prompt(task: SWETask, config: HarnessConfig) -> str:
    """Build the prompt sent to the solver agent."""
    return f"""## GitHub Issue to Solve

**Repository:** {task.repo}
**Instance ID:** {task.instance_id}

### Problem Statement

{task.problem_statement}

---

The repository is already cloned in your working directory and checked out at commit `{task.base_commit}`.

Explore the repository, understand the code, and fix the issue.
Make minimal changes, do not create branches or commits, just edit the files directly.
"""


async def solve_swe_task(
    task: SWETask,
    agent_id: str,
    workspace_dir: Path,
    ref_repo_dir: Path,
    config: HarnessConfig,
    trace_data: AgentTraceData,
    agent_api_key: str = "",
) -> dict:
    """
    Run a solver agent on a SWE-bench task.

    Args:
        task: The SWE-bench task to solve
        agent_id: Unique agent identifier
        workspace_dir: Isolated workspace directory for this agent
        ref_repo_dir: Pre-cloned reference repo to copy from
        config: Harness configuration
        trace_data: Tracing data accumulator
        agent_api_key: Optional ChatOverflow API key for this agent

    Returns:
        Dict with instance_id, model_patch, model_name_or_path, and metadata
    """
    start_time = time.time()

    # Setup workspace by copying from reference repo (fast local copy)
    try:
        repo_dir = await asyncio.to_thread(
            setup_workspace, task, workspace_dir, ref_repo_dir
        )
    except Exception as e:
        logger.error(f"[{agent_id}] Failed to setup workspace: {e}")
        trace_data.error = f"workspace_setup: {e}"
        return {
            "instance_id": task.instance_id,
            "model_name_or_path": f"kekule-{config.model}",
            "model_patch": "",
            "agent_id": agent_id,
            "error": str(e),
        }

    # Build Claude Agent SDK options
    hooks = build_agent_hooks(trace_data)

    # Build system prompt
    system_prompt = SWE_SOLVER_SYSTEM_PROMPT
    if config.enable_chatoverflow:
        system_prompt += CHATOVERFLOW_SWE_SKILL_PROMPT.format(
            chatoverflow_api_url=config.chatoverflow_api_url,
        )

    env = {}
    if config.enable_chatoverflow and agent_api_key:
        env["CHATOVERFLOW_API_URL"] = config.chatoverflow_api_url
        env["CHATOVERFLOW_API_KEY"] = agent_api_key

    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": system_prompt,
        },
        model=config.model,
        permission_mode="bypassPermissions",
        cwd=str(repo_dir),
        allowed_tools=[
            "Bash",
            "Read",
            "Write",
            "Edit",
            "Glob",
            "Grep",
            "Task",
            "WebFetch",
        ],
        setting_sources=["project", "local"],
        env=env,
        max_turns=config.max_agent_turns,
        hooks=hooks,
    )

    prompt = build_swe_prompt(task, config)
    trace_data.prompt = prompt

    logger.info(f"[{agent_id}] Starting solver for {task.instance_id}")

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                # Serialize content blocks for tracing
                content_dicts = []
                for block in message.content:
                    if isinstance(block, TextBlock):
                        content_dicts.append({"type": "text", "text": block.text})
                        if len(block.text) > 100:
                            logger.debug(
                                f"[{agent_id}] text: {block.text[:100]}..."
                            )
                    elif isinstance(block, ToolUseBlock):
                        content_dicts.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                        logger.info(f"[{agent_id}] tool: {block.name}")

                trace_data.messages.append({
                    "type": "assistant",
                    "model": message.model,
                    "content": content_dicts,
                })

            elif isinstance(message, UserMessage):
                # Capture tool results from user messages
                if isinstance(message.content, list):
                    for block in message.content:
                        if isinstance(block, ToolResultBlock):
                            trace_data.messages.append({
                                "type": "tool_result",
                                "tool_use_id": block.tool_use_id,
                                "content": str(block.content)[:2000] if block.content else "",
                                "is_error": block.is_error or False,
                            })

            elif isinstance(message, ResultMessage):
                trace_data.num_turns = message.num_turns
                trace_data.total_cost_usd = message.total_cost_usd or 0.0
                logger.info(
                    f"[{agent_id}] Completed: turns={message.num_turns}, "
                    f"cost=${message.total_cost_usd or 0:.4f}, "
                    f"error={message.is_error}"
                )
                if message.is_error:
                    trace_data.error = f"agent_error: {message.result}"

    except Exception as e:
        logger.error(f"[{agent_id}] Agent failed: {e}")
        trace_data.error = f"agent_exception: {e}"

    # Extract the patch
    patch = extract_patch(repo_dir)
    trace_data.patch_produced = bool(patch.strip())
    trace_data.patch_content = patch

    elapsed = time.time() - start_time
    logger.info(
        f"[{agent_id}] Finished in {elapsed:.1f}s, "
        f"patch={'yes' if patch.strip() else 'no'} "
        f"({len(patch)} bytes)"
    )

    return {
        "instance_id": task.instance_id,
        "model_name_or_path": f"kekule-{config.model}",
        "model_patch": patch,
        "agent_id": agent_id,
        "duration_s": elapsed,
        "num_turns": trace_data.num_turns,
        "cost_usd": trace_data.total_cost_usd,
    }
