import pytest
import importlib.util
from pathlib import Path


def _load_runner_module():
    runner_path = Path(__file__).resolve().parents[1] / "experiments" / "run_tool_io_reliability.py"
    spec = importlib.util.spec_from_file_location("run_tool_io_reliability", runner_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_enforce_patch_integrity_sanitizes_rows():
    module = _load_runner_module()
    rows = [
        {
            "instance_id": "django__django-14915",
            "model_patch": """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-print("old")
+print("new")
diff --git a/docs/_theme/djangodocs-epub/static/docicons-icon b/docs/_theme/djangodocs-epub/static/docicons-icon
old mode 120000
new mode 100644
--- a/docs/_theme/djangodocs-epub/static/docicons-icon
+++ b/docs/_theme/djangodocs-epub/static/docicons-icon
@@ -1 +1 @@
-old
+new
""",
        }
    ]

    sanitized = module._enforce_patch_integrity(rows, "run-1")
    assert len(sanitized) == 1
    assert "src/app.py" in sanitized[0]["model_patch"]
    assert "docicons-icon" not in sanitized[0]["model_patch"]


def test_enforce_patch_integrity_raises_on_empty_rows():
    module = _load_runner_module()
    rows = [{"instance_id": "django__django-14915", "model_patch": ""}]
    with pytest.raises(RuntimeError, match="unevaluable rows"):
        module._enforce_patch_integrity(rows, "run-1")


def test_enforce_patch_integrity_raises_on_rejected_patch():
    module = _load_runner_module()
    rows = [
        {
            "instance_id": "django__django-14915",
            "model_patch": """diff --git a/src/link.txt b/src/link.txt
new file mode 120000
index 0000000..1111111
--- /dev/null
+++ b/src/link.txt
@@ -0,0 +1 @@
+target.txt
""",
        }
    ]
    with pytest.raises(RuntimeError, match="unevaluable rows"):
        module._enforce_patch_integrity(rows, "run-1")
