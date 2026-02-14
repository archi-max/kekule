from kekule.benchmarks.patch_hygiene import (
    extract_changed_files,
    sanitize_patch,
)


def test_sanitize_patch_drops_noisy_docicons_section():
    patch = """diff --git a/src/app.py b/src/app.py
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
"""
    result = sanitize_patch(patch, fail_closed_on_special=True)

    assert result.rejected is False
    assert "src/app.py" in result.patch
    assert "docicons-icon" not in result.patch
    assert "docs/_theme/djangodocs-epub/static/docicons-icon" in result.dropped_files


def test_sanitize_patch_rejects_symlink_sections_when_fail_closed():
    patch = """diff --git a/src/link.txt b/src/link.txt
new file mode 120000
index 0000000..1111111
--- /dev/null
+++ b/src/link.txt
@@ -0,0 +1 @@
+target.txt
"""
    result = sanitize_patch(patch, fail_closed_on_special=True)

    assert result.rejected is True
    assert result.patch == ""
    assert result.reason.startswith("special_hunk:")


def test_sanitize_patch_respects_allowed_files():
    patch = """diff --git a/src/a.py b/src/a.py
index 1111111..2222222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-a = 1
+a = 2
diff --git a/src/b.py b/src/b.py
index 3333333..4444444 100644
--- a/src/b.py
+++ b/src/b.py
@@ -1 +1 @@
-b = 1
+b = 2
"""
    result = sanitize_patch(
        patch,
        allowed_files={"src/b.py"},
        fail_closed_on_special=True,
    )

    assert result.rejected is False
    assert "src/b.py" in result.patch
    assert "src/a.py" not in result.patch
    assert result.kept_files == ("src/b.py",)


def test_extract_changed_files_reads_paths():
    patch = """diff --git a/src/a.py b/src/a.py
index 1111111..2222222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-a = 1
+a = 2
diff --git a/src/b.py b/src/b.py
index 3333333..4444444 100644
--- a/src/b.py
+++ b/src/b.py
@@ -1 +1 @@
-b = 1
+b = 2
"""
    files = extract_changed_files(patch)
    assert files == {"src/a.py", "src/b.py"}
