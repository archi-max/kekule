import json

from kekule.benchmarks.evaluator import write_predictions


def test_write_predictions_drops_noisy_sections(tmp_path):
    results = [
        {
            "instance_id": "django__django-14915",
            "agent_id": "agent-1",
            "model_name_or_path": "kekule",
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

    output = write_predictions(results, tmp_path, "case")
    line = output.read_text().strip()
    payload = json.loads(line)

    assert "src/app.py" in payload["model_patch"]
    assert "docicons-icon" not in payload["model_patch"]


def test_write_predictions_rejects_symlink_patch(tmp_path):
    results = [
        {
            "instance_id": "django__django-14915",
            "agent_id": "agent-1",
            "model_name_or_path": "kekule",
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

    output = write_predictions(results, tmp_path, "case")
    line = output.read_text().strip()
    payload = json.loads(line)

    assert payload["model_patch"] == ""
