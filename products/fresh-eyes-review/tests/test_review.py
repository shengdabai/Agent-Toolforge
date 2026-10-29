"""Tests for the fresh-eyes-review core helper (review.py).

Standard-library unittest only. No third-party dependencies, no network.
"""
import os
import sys
import unittest

# Make the package source importable regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import review  # noqa: E402


SAMPLE_DIFF_SINGLE = """\
--- a/app/calc.py
+++ b/app/calc.py
@@ -1,4 +1,5 @@
 def add(a, b):
-    return a + b
+    # new behavior
+    return a + b + 0
 def sub(a, b):
     return a - b
"""

SAMPLE_DIFF_MULTI = """\
diff --git a/src/one.py b/src/one.py
--- a/src/one.py
+++ b/src/one.py
@@ -1,2 +1,3 @@
 import os
+import sys
 print("one")
diff --git a/src/two.py b/src/two.py
--- a/src/two.py
+++ b/src/two.py
@@ -10,3 +10,2 @@
 def f():
-    x = 1
-    return x
+    return 1
"""


class TestBuildReviewPrompt(unittest.TestCase):
    def test_prompt_contains_adversarial_disavowal(self):
        prompt = review.build_review_prompt(SAMPLE_DIFF_SINGLE)
        self.assertIn("You did NOT write this code. Review it adversarially.", prompt)

    def test_prompt_contains_severity_rubric(self):
        prompt = review.build_review_prompt(SAMPLE_DIFF_SINGLE)
        lowered = prompt.lower()
        # All three severity tiers must be present.
        self.assertIn("critical", lowered)
        self.assertIn("major", lowered)
        self.assertIn("minor", lowered)
        # And the word "severity" must frame the rubric.
        self.assertIn("severity", lowered)

    def test_prompt_embeds_the_diff(self):
        prompt = review.build_review_prompt(SAMPLE_DIFF_SINGLE)
        self.assertIn("return a + b + 0", prompt)

    def test_empty_checklist_falls_back_to_default(self):
        # checklist=None must inject the default checklist categories.
        prompt = review.build_review_prompt(SAMPLE_DIFF_SINGLE, checklist=None)
        lowered = prompt.lower()
        for category in ("correctness", "security", "edge", "error handling", "duplicat"):
            self.assertIn(category, lowered)

    def test_empty_list_checklist_also_falls_back_to_default(self):
        prompt = review.build_review_prompt(SAMPLE_DIFF_SINGLE, checklist=[])
        lowered = prompt.lower()
        self.assertIn("correctness", lowered)
        self.assertIn("security", lowered)

    def test_custom_checklist_is_used(self):
        prompt = review.build_review_prompt(
            SAMPLE_DIFF_SINGLE, checklist=["Race conditions", "Memory leaks"]
        )
        self.assertIn("Race conditions", prompt)
        self.assertIn("Memory leaks", prompt)
        # Default categories should NOT be auto-added when a custom list is given.
        self.assertNotIn("Duplication", prompt)

    def test_context_is_included_when_provided(self):
        prompt = review.build_review_prompt(
            SAMPLE_DIFF_SINGLE, context="This is a payments service. PCI scope."
        )
        self.assertIn("PCI scope", prompt)

    def test_context_section_absent_when_none(self):
        prompt = review.build_review_prompt(SAMPLE_DIFF_SINGLE, context=None)
        # Should not leave a dangling empty context header.
        self.assertNotIn("PCI scope", prompt)

    def test_severity_definitions_present(self):
        prompt = review.build_review_prompt(SAMPLE_DIFF_SINGLE)
        lowered = prompt.lower()
        # Rubric should define what each tier means, not just name them.
        self.assertIn("block", lowered)  # critical => block merge


class TestParseDiff(unittest.TestCase):
    def test_single_file(self):
        result = review.parse_diff(SAMPLE_DIFF_SINGLE)
        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry["file"], "app/calc.py")
        self.assertEqual(entry["added_lines"], 2)
        self.assertEqual(entry["removed_lines"], 1)

    def test_multi_file(self):
        result = review.parse_diff(SAMPLE_DIFF_MULTI)
        files = {e["file"]: e for e in result}
        self.assertEqual(set(files), {"src/one.py", "src/two.py"})
        self.assertEqual(files["src/one.py"]["added_lines"], 1)
        self.assertEqual(files["src/one.py"]["removed_lines"], 0)
        self.assertEqual(files["src/two.py"]["added_lines"], 1)
        self.assertEqual(files["src/two.py"]["removed_lines"], 2)

    def test_does_not_count_hunk_header_or_metadata_as_changes(self):
        # The +++ / --- header lines and @@ hunk lines must be excluded.
        result = review.parse_diff(SAMPLE_DIFF_SINGLE)
        self.assertEqual(result[0]["added_lines"], 2)
        self.assertEqual(result[0]["removed_lines"], 1)

    def test_no_diff_header_returns_empty(self):
        # Plain text with no recognizable file headers => graceful empty list.
        result = review.parse_diff("just some random text\nwith no diff markers\n")
        self.assertEqual(result, [])

    def test_rename_metadata_without_a_file_header_is_not_a_diff(self):
        self.assertEqual(review.parse_diff("rename to unrelated.txt\n"), [])

    def test_git_no_prefix_header_is_still_supported(self):
        self.assertEqual(review.parse_diff(
            "diff --git image.png image.png\nBinary files image.png and image.png differ\n"
        ), [{"file": "image.png", "added_lines": 0, "removed_lines": 0}])

    def test_empty_string(self):
        self.assertEqual(review.parse_diff(""), [])

    def test_none_input_is_graceful(self):
        self.assertEqual(review.parse_diff(None), [])

    def test_added_only_file(self):
        diff = (
            "--- a/new.txt\n"
            "+++ b/new.txt\n"
            "@@ -0,0 +1,2 @@\n"
            "+line one\n"
            "+line two\n"
        )
        result = review.parse_diff(diff)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["file"], "new.txt")
        self.assertEqual(result[0]["added_lines"], 2)
        self.assertEqual(result[0]["removed_lines"], 0)

    def test_prefix_stripping_handles_dev_null(self):
        # A deletion: +++ b/dev/null style should still resolve a file name.
        diff = (
            "--- a/gone.py\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-a\n"
            "-b\n"
        )
        result = review.parse_diff(diff)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["file"], "gone.py")
        self.assertEqual(result[0]["removed_lines"], 2)
        self.assertEqual(result[0]["added_lines"], 0)

    def test_git_paths_with_spaces_do_not_create_phantom_files(self):
        diff = ("diff --git a/my file.txt b/my file.txt\n"
                "--- a/my file.txt\n+++ b/my file.txt\n"
                "@@ -1 +1 @@\n-old\n+new\n")
        self.assertEqual(review.parse_diff(diff), [
            {"file": "my file.txt", "added_lines": 1, "removed_lines": 1},
        ])

    def test_git_quoted_paths_are_decoded(self):
        diff = ('diff --git "a/my\\tfile.txt" "b/my\\tfile.txt"\n'
                '--- "a/my\\tfile.txt"\n+++ "b/my\\tfile.txt"\n'
                '@@ -1 +1 @@\n-old\n+new\n')
        self.assertEqual(review.parse_diff(diff), [
            {"file": "my\tfile.txt", "added_lines": 1, "removed_lines": 1},
        ])

    def test_git_utf8_octal_paths_are_decoded(self):
        path = r'\344\275\240\345\245\275.py'
        diff = ('diff --git "a/' + path + '" "b/' + path + '"\n'
                '--- "a/' + path + '"\n+++ "b/' + path + '"\n'
                '@@ -1 +1 @@\n-old\n+new\n')
        self.assertEqual(review.parse_diff(diff), [
            {"file": "你好.py", "added_lines": 1, "removed_lines": 1},
        ])

    def test_header_paths_containing_b_slash_use_post_image_header(self):
        diff = ("diff --git a/has b/file b/has b/file\n"
                "index 1111111..2222222 100644\n"
                "--- a/has b/file\n+++ b/has b/file\n"
                "@@ -1 +1 @@\n-old\n+new\n")
        self.assertEqual(review.parse_diff(diff), [
            {"file": "has b/file", "added_lines": 1, "removed_lines": 1},
        ])

    def test_empty_added_file_with_b_slash_has_no_post_image_header(self):
        diff = ("diff --git a/has b/empty file.txt b/has b/empty file.txt\n"
                "new file mode 100644\nindex 0000000..e69de29\n")
        self.assertEqual(review.parse_diff(diff), [
            {"file": "has b/empty file.txt", "added_lines": 0, "removed_lines": 0},
        ])

    def test_plain_diff_uses_post_image_path_without_phantom_old_file(self):
        diff = ("--- before.txt\t2026-01-01\n+++ after.txt\t2026-01-02\n"
                "@@ -1 +1 @@\n-old\n+new\n")
        self.assertEqual(review.parse_diff(diff), [
            {"file": "after.txt", "added_lines": 1, "removed_lines": 1},
        ])

    def test_plain_multi_file_diff_keeps_deletion_separate(self):
        diff = ("--- a/first\n+++ b/first\n@@ -1 +1 @@\n-old\n+new\n"
                "--- a/gone\n+++ /dev/null\n@@ -1 +0,0 @@\n-removed\n")
        self.assertEqual(review.parse_diff(diff), [
            {"file": "first", "added_lines": 1, "removed_lines": 1},
            {"file": "gone", "added_lines": 0, "removed_lines": 1},
        ])

    def test_git_rename_only_with_spaces_uses_destination(self):
        diff = ("diff --git a/old name.txt b/new name.txt\n"
                "similarity index 100%\nrename from old name.txt\n"
                "rename to new name.txt\n")
        self.assertEqual(review.parse_diff(diff), [
            {"file": "new name.txt", "added_lines": 0, "removed_lines": 0},
        ])

    def test_git_rename_metadata_preserves_real_a_directory(self):
        diff = ("diff --git a/old b/a/new b/name.txt\n"
                "similarity index 100%\nrename from old\n"
                "rename to a/new b/name.txt\n")
        self.assertEqual(review.parse_diff(diff), [
            {"file": "a/new b/name.txt", "added_lines": 0, "removed_lines": 0},
        ])


class TestEndToEnd(unittest.TestCase):
    def test_prompt_reports_changed_file_summary(self):
        # build_review_prompt should surface the parsed file summary so the
        # reviewer knows the blast radius.
        prompt = review.build_review_prompt(SAMPLE_DIFF_MULTI)
        self.assertIn("src/one.py", prompt)
        self.assertIn("src/two.py", prompt)


class TestB11HunkAwareParsing(unittest.TestCase):
    def test_content_lines_that_look_like_headers_are_counted(self):
        diff = (
            "diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n"
            "@@ -1,2 +1,2 @@\n--- old comment\n+++ new comment\n"
            "-select 1;\n+select 2;\n"
            "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n"
            "@@ -3 +3 @@\n-x\n+y\n\\ No newline at end of file\n"
        )
        self.assertEqual(review.parse_diff(diff), [
            {"file": "q.sql", "added_lines": 2, "removed_lines": 2},
            {"file": "b.py", "added_lines": 1, "removed_lines": 1},
        ])

    def test_malformed_hunk_header_falls_back(self):
        diff = "--- a/x\n+++ b/x\n@@ garbage @@\n+a\n-b\n"
        self.assertEqual(review.parse_diff(diff),
                         [{"file": "x", "added_lines": 1, "removed_lines": 1}])

    def test_short_hunk_does_not_swallow_next_file(self):
        diff = ("--- a/x\n+++ b/x\n@@ -1,9 +1,9 @@\n+a\n"
                "diff --git a/y b/y\n--- a/y\n+++ b/y\n@@ -1 +1 @@\n-o\n+n\n")
        self.assertEqual(review.parse_diff(diff), [
            {"file": "x", "added_lines": 1, "removed_lines": 0},
            {"file": "y", "added_lines": 1, "removed_lines": 1},
        ])

    def test_orphan_hunk_before_first_git_header_does_not_crash(self):
        diff = ("@@ -1 +1 @@\ndiff --git a/y b/y\n--- a/y\n+++ b/y\n"
                "@@ -1 +1 @@\n-a\n+b\n")
        self.assertEqual(review.parse_diff(diff),
                         [{"file": "y", "added_lines": 1, "removed_lines": 1}])


if __name__ == "__main__":
    unittest.main()
