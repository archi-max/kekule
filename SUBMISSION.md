# Hackathon Submission: Kekule

**Built for**: [Built with Opus 4.6: a Claude Code Hackathon](https://cerebralvalley.ai/) (Cerebral Valley & Anthropic)

**Team**: [Ansh Tulsyan](https://github.com/archi-max) & [Jack Armitage](https://github.com/jarmitage)

---

## Problem Statement

**Primary: Problem Statement Three — Amplify Human Judgment**

Kekule amplifies researchers running AI coding experiments. The researcher defines the task set, chooses solvers, and steers through Claude Code -- but the diagnosis-to-adaptation loop runs autonomously. The system surfaces structured failure analysis, evolving verification strategies, and score progressions so the researcher makes better decisions about what to try next, without manually reading logs and rewriting prompts.

**Secondary: Problem Statement One — Build a Tool That Should Exist**

The feedback loop between "my agents failed" and "here's a structurally different approach" doesn't exist today. Researchers close it by hand. Kekule automates it.

---

## Project Description

AI agent benchmarks today are static: run agents, score results, manually tweak prompts, repeat. Researchers spend more time diagnosing failures and hand-tuning strategies than running experiments. The feedback loop between "what went wrong" and "what to try next" is entirely manual -- and it doesn't scale.

Kekule is a Claude Code skill that closes this loop. You define a task set and point kekule-bench at it. A swarm of Claude agents solves tasks, then the system runs its own retrospective: a failure analyst diagnoses why each fix broke, a coordinator distills generic lessons and invents new verification strategies, and the next epoch runs with a rewritten playbook. A train/test split prevents overfitting. You steer experiments through Claude Code and share results through a dashboard.

The verification engine evolves autonomously. In our first experiment, the coordinator invented 5 oracle strategies that didn't exist at startup. A failing 7KB patch shrank to 742 bytes after it learned "don't replace library functions." We targeted SWE-bench tasks the current SOTA couldn't solve and resolved 2.

Every agent is a Claude instance via the Agent SDK. Opus 4.6 runs the coordinator brain.
