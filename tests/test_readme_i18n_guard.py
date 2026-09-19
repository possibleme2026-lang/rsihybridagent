# Copyright 2026 The rsihybridagent Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for the README drift guard.

The guard exists because two README files drift. Its own failure mode is worse than the
drift: a guard that compares too little stops catching drift, and a guard that compares
too much fails on a legitimate difference and gets disabled. Both are tested here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "check_readme_i18n.py"


def _load() -> object:
    """Import the guard script, which is not part of the installed package."""
    spec = importlib.util.spec_from_file_location("check_readme_i18n", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_readme_i18n"] = module
    spec.loader.exec_module(module)
    return module


guard = _load()


class TestStripComments:
    """The comment stripper is what lets a translated annotation pass while a changed command fails."""

    def test_a_trailing_comment_is_dropped_but_the_command_survives(self) -> None:
        """A shell example annotates its command on the same line, in the file's language."""
        english = "rsihybrid extensions  # what is installed"
        chinese = "rsihybrid extensions  # 已安装了什么"
        assert guard.strip_comments("bash", english) == guard.strip_comments("bash", chinese)
        assert "rsihybrid extensions" in guard.strip_comments("bash", chinese)

    def test_a_whole_line_comment_is_dropped(self) -> None:
        """A comment on its own line carries no executable content."""
        assert guard.strip_comments("bash", "# a note\npytest -q") == "pytest -q"

    def test_a_changed_command_is_still_caught(self) -> None:
        """The point of stripping comments: a real command change must still differ."""
        assert guard.strip_comments("bash", "pytest -q  # run tests") != guard.strip_comments("bash", "pytest -v")

    def test_a_hash_inside_a_command_is_kept(self) -> None:
        """A ``#`` that is part of the command text is not a comment.

        This is the failure that would matter in practice: a URL fragment or a colour
        literal would be truncated, and a genuine difference after it would go unnoticed.
        """
        line = "git clone https://example.com/repo#main"
        assert guard.strip_comments("bash", line) == "git clone https://example.com/repo"

    def test_bibtex_keeps_everything(self) -> None:
        """Bibtex is not comment-stripped: a citation must match byte for byte."""
        body = "@misc{k,\n  title={A # B},\n}"
        assert guard.strip_comments("bibtex", body) == body

    def test_python_comments_are_stripped_like_shell(self) -> None:
        """A code sample's comment may be translated, exactly as a shell one may."""
        english = "x = call()  # run it"
        chinese = "x = call()  # 运行它"
        assert guard.strip_comments("python", english) == guard.strip_comments("python", chinese)

    def test_blank_lines_and_indentation_are_normalized(self) -> None:
        """Whitespace-only differences must not read as drift."""
        assert guard.strip_comments("bash", "a\n\n   \nb") == "a\nb"


class TestPythonCodeBlocks:
    """A code sample is not prose: a translated comment is fine, a changed call is drift.

    This is the case that matters most, because a README's code is what a reader copies.
    A block that drifted would hand someone a call that does not exist, and nothing else
    in the toolchain would notice — the sample is not imported by anything.
    """

    def test_a_translated_comment_passes(self) -> None:
        """Translating a comment must not be reported as drift."""
        english = "```python\nx = call()  # run it\n```"
        chinese = "```python\nx = call()  # 运行它\n```"
        assert guard.check_machine_readable_blocks(english, chinese) == []

    def test_a_changed_api_call_is_caught(self) -> None:
        """The call itself is the thing a reader copies, so it must match."""
        english = "```python\nx = call()\n```"
        chinese = "```python\nx = other_call()\n```"
        assert guard.check_machine_readable_blocks(english, chinese) != []

    def test_a_changed_keyword_argument_is_caught(self) -> None:
        """A changed argument changes the meaning of the sample."""
        english = "```python\nx = call()\n```"
        chinese = "```python\nx = call(verbose=True)\n```"
        assert guard.check_machine_readable_blocks(english, chinese) != []

    def test_a_dropped_code_line_is_caught(self) -> None:
        """Dropping the only executable line leaves an empty sample, which is drift."""
        english = "```python\nx = call()\n```"
        chinese = "```python\n# 运行它\n```"
        assert guard.check_machine_readable_blocks(english, chinese) != []

    def test_a_missing_block_is_caught(self) -> None:
        """A sample present in one file and absent in the other is drift."""
        english = "```python\nx = call()\n```"
        chinese = "no sample here"
        assert guard.check_machine_readable_blocks(english, chinese) != []


class TestChecks:
    """Each check must fail on real drift and pass on a legitimate translation."""

    def test_identical_structures_pass(self) -> None:
        """Two files with the same shape are reported as in sync."""
        body = "## One\n\ntext\n\n## Two\n\nmore\n"
        assert guard.check_headings(body, body) == []

    def test_a_missing_section_is_caught(self) -> None:
        """A section present in one file and absent in the other is drift."""
        english = "## One\n\n## Two\n"
        chinese = "## One\n"
        assert guard.check_headings(english, chinese) != []

    def test_a_changed_heading_depth_is_caught(self) -> None:
        """A section demoted from ``##`` to ``###`` is a structural difference."""
        english = "## One\n\n## Two\n"
        chinese = "## One\n\n### Two\n"
        assert guard.check_headings(english, chinese) != []

    def test_translated_headings_are_not_drift(self) -> None:
        """Headings are compared by depth, never by text: the files are different languages."""
        english = "## Why it is needed\n\n## Status\n"
        chinese = "## 为什么需要\n\n## 状态\n"
        assert guard.check_headings(english, chinese) == []

    def test_a_link_only_in_one_file_is_caught(self) -> None:
        """A reference dropped from one file must be reported."""
        english = "[a](https://example.com/a)"
        chinese = "[a](https://example.com/b)"
        problems = guard.check_external_links(english, chinese)
        assert any("example.com/a" in p for p in problems)
        assert any("example.com/b" in p for p in problems)

    def test_identical_links_pass(self) -> None:
        """The same reference set is what both files must cite."""
        english = "[a](https://example.com/a) [b](https://example.com/b)"
        chinese = "[甲](https://example.com/a) [乙](https://example.com/b)"
        assert guard.check_external_links(english, chinese) == []

    def test_a_broken_relative_link_is_caught(self) -> None:
        """A relative link that does not resolve on disk is a dead link."""
        problems = guard.check_internal_links("", "[x](no/such/file.md)")
        assert any("no/such/file.md" in p for p in problems)

    def test_a_language_switch_is_required(self) -> None:
        """Without a cross-link a reader is stranded in one language."""
        assert guard.check_language_switch("nothing here", "nothing here") != []
        assert guard.check_language_switch("see README.zh-CN.md", "see README.md") == []


class TestAgainstTheRealFiles:
    """The guard must pass on the repository's actual READMEs."""

    def test_the_repository_readmes_are_in_sync(self) -> None:
        """A failure here means the two files have genuinely drifted."""
        assert guard.main() == 0


@pytest.mark.parametrize("language", ["bash", "toml", "bibtex", "python"])
def test_machine_readable_languages_are_covered(language: str) -> None:
    """Every language the guard treats as non-prose is actually in its list."""
    assert language in guard.MACHINE_READABLE_LANGUAGES
