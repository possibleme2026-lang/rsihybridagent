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

"""Keeps ``docs/interfaces.md`` honest about the signatures it documents.

The document exists so that someone implementing an extension can read one file instead
of the source, which makes a stale signature worse than no signature: it is wrong with
the authority of documentation. This actually happened. A refactor turned ``kind``,
``health``, ``repository`` and ``channel`` from properties into methods and replaced
``Recipe.surface`` with ``target_surface()``; every test passed, the README linked to the
document, and the document still described the superseded API. Nothing failed because
prose is not compiled.

The check is structural, not textual. Rewriting a sentence, adding an explanation, or
changing an example does not trip it; adding an abstract method without documenting it,
documenting one that does not exist, or disagreeing about whether a member is a property
does. That is the same line the README i18n guard draws: compare shape, not wording.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from rsihybridagent.artifact import ArtifactRepository
from rsihybridagent.core import Substrate, Surface
from rsihybridagent.interlock.base import CrossingConsumer, CrossingProducer, InterlockPort
from rsihybridagent.ledger.base import AdmissionPolicy, Ledger
from rsihybridagent.loop import Recipe, Verifier

DOC = Path(__file__).resolve().parents[1] / "docs" / "interfaces.md"

#: Every class whose members the document claims to enumerate.
#:
#: A class is listed here because the document presents it as a contract to implement,
#: so its abstract members are the thing a reader copies. Value types such as
#: ``ArtifactRef`` are deliberately absent: the document shows their fields, and a field
#: list is not a contract the code can be compared against by method name.
CONTRACTS: dict[str, type] = {
    "Substrate": Substrate,
    "Surface": Surface,
    "ArtifactRepository": ArtifactRepository,
    "Recipe": Recipe,
    "Verifier": Verifier,
    "Ledger": Ledger,
    "AdmissionPolicy": AdmissionPolicy,
    "InterlockPort": InterlockPort,
    "CrossingProducer": CrossingProducer,
    "CrossingConsumer": CrossingConsumer,
}


def _doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def _documented_members(text: str, class_name: str) -> dict[str, bool]:
    """Members the document shows for a class, mapped to whether it calls them properties.

    Only the first fenced block that declares the class is read. The document discusses
    some classes twice — once as a signature and once as an illustration of a mistake —
    and folding those together would compare a counter-example against the contract.

    The block ends at the next class or at a top-level ``def``, so a module-level helper
    shown after a class (``validate_crossing``) is not read as one of its members.
    """
    pattern = re.compile(
        rf"^class {re.escape(class_name)}\(.*?\):\n(?P<body>.*?)(?=^class |^def |^```)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        return {}

    members: dict[str, bool] = {}
    pending_property = False
    for line in match.group("body").splitlines():
        stripped = line.strip()
        if stripped == "@property":
            pending_property = True
            continue
        if stripped.startswith("@") or not stripped:
            continue
        found = re.match(r"def (\w+)\(", stripped)
        if found:
            members[found.group(1)] = pending_property
            pending_property = False
    return members


def _abstract_members(cls: type) -> dict[str, bool]:
    """The class's abstract members, mapped to whether each is a property."""
    members: dict[str, bool] = {}
    for name, value in vars(cls).items():
        if name.startswith("__"):
            continue
        if isinstance(value, property):
            # A property is abstract when its fget carries __isabstractmethod__.
            if getattr(value.fget, "__isabstractmethod__", False):
                members[name] = True
            continue
        if getattr(value, "__isabstractmethod__", False):
            members[name] = False
    return members


@pytest.mark.parametrize("class_name", sorted(CONTRACTS))
def test_the_document_shows_every_abstract_member(class_name: str) -> None:
    """An abstract member the document omits is one a reader will not implement.

    The failure is a ``TypeError`` at instantiation, far from the document that caused it.
    """
    documented = _documented_members(_doc_text(), class_name)
    expected = _abstract_members(CONTRACTS[class_name])
    missing = sorted(set(expected) - set(documented))
    assert not missing, (
        f"docs/interfaces.md does not show {class_name}.{', '.join(missing)}; "
        f"a reader implementing this contract would not know the member exists"
    )


@pytest.mark.parametrize("class_name", sorted(CONTRACTS))
def test_the_document_shows_no_member_that_does_not_exist(class_name: str) -> None:
    """A documented member that is absent is an instruction to write code that cannot run."""
    documented = _documented_members(_doc_text(), class_name)
    expected = _abstract_members(CONTRACTS[class_name])
    extra = sorted(set(documented) - set(expected))
    assert not extra, (
        f"docs/interfaces.md shows {class_name}.{', '.join(extra)}, "
        f"which is not an abstract member of {CONTRACTS[class_name].__name__}"
    )


@pytest.mark.parametrize("class_name", sorted(CONTRACTS))
def test_the_document_agrees_on_property_versus_method(class_name: str) -> None:
    """A property in the document and a method in the code is the defect this guard exists for.

    ``@property`` with ``@abstractmethod`` cannot be satisfied by a dataclass field of the
    same name, so the two are not interchangeable in either direction: documenting a
    property tells the reader to implement something that will not satisfy the class, and
    documenting a method as a property tells them to expect an attribute.
    """
    documented = _documented_members(_doc_text(), class_name)
    expected = _abstract_members(CONTRACTS[class_name])
    disagreements = [
        name
        for name, is_property in documented.items()
        if name in expected and is_property != expected[name]
    ]
    assert not disagreements, (
        f"docs/interfaces.md and {class_name} disagree on whether "
        f"{', '.join(disagreements)} is a property: the document says property, "
        f"the code says method"
    )


def test_every_contract_class_appears_in_the_document() -> None:
    """A contract with no section is a contract nobody reads.

    Checked separately from the member comparison because a missing class would otherwise
    pass every per-class test by being absent from both sides.
    """
    text = _doc_text()
    absent = [name for name in CONTRACTS if f"class {name}(" not in text]
    assert not absent, f"docs/interfaces.md has no signature block for: {', '.join(sorted(absent))}"


def test_the_document_names_the_real_cli_command() -> None:
    """The document tells a reader which command to run, so it must be the one that exists.

    ``pyproject.toml`` declares the console script as ``rsihybrid``. The package name is
    ``rsihybridagent``, so the wrong command is the natural guess and was in the document
    until this test was written.
    """
    from rsihybridagent import cli

    text = _doc_text()
    assert "rsihybrid " in text or "rsihybrid\n" in text, "docs/interfaces.md does not show the CLI command"
    assert "rsihybridagent extensions" not in text, (
        "docs/interfaces.md shows 'rsihybridagent extensions'; the console script is 'rsihybrid'"
    )
    assert callable(cli.main)


def test_the_documented_extension_point_values_match_the_enum() -> None:
    """The group names are what a third-party package writes into its own pyproject.

    A wrong group name there fails silently in the sense that matters: the package
    installs, the entry point is declared, and the backend is never found.
    """
    from rsihybridagent.registry import ExtensionPoint

    text = _doc_text()
    for point in ExtensionPoint:
        assert point.value in text, f"docs/interfaces.md does not name the group {point.value!r}"


def test_the_document_is_not_empty() -> None:
    """A guard over an unreadable file would pass vacuously."""
    assert len(_doc_text()) > 2000
    assert inspect.ismodule(inspect.getmodule(Substrate))


class TestTheGuardItselfCatchesDrift:
    """Negative tests: the comparison must fail on the defect it was written for.

    A guard that passes on both correct and incorrect input is worse than no guard, because
    it certifies the document. These feed the helpers the exact text that was in the file
    before the refactor, so the check is proven to detect a recurrence rather than assumed to.
    """

    def test_a_property_where_the_code_has_a_method_is_caught(self) -> None:
        """The original defect: ``Substrate.kind`` documented as a property."""
        text = _doc_text().replace(
            "class Substrate(ABC):\n    @abstractmethod\n    def kind",
            "class Substrate(ABC):\n    @property\n    @abstractmethod\n    def kind",
            1,
        )
        documented = _documented_members(text, "Substrate")
        assert documented["kind"] is True
        assert _abstract_members(Substrate)["kind"] is False

    def test_a_renamed_method_is_caught(self) -> None:
        """``Recipe.surface`` was replaced by ``target_surface()``; both directions must fail."""
        text = _doc_text().replace(
            "class Recipe(ABC):\n    @abstractmethod\n    def target_surface",
            "class Recipe(ABC):\n    @abstractmethod\n    def surface",
            1,
        )
        documented = _documented_members(text, "Recipe")
        expected = _abstract_members(Recipe)
        assert "surface" in documented and "surface" not in expected
        assert "target_surface" in expected and "target_surface" not in documented

    def test_a_dropped_member_is_caught(self) -> None:
        """A member removed from the document but still in the code is a missing entry."""
        rollback_line = "    def rollback(self, *, scenario: ScenarioId) -> ArtifactRef | None: ...\n"
        text = _doc_text().replace(rollback_line, "", 1)
        assert "rollback" not in _documented_members(text, "Surface")
        assert "rollback" in _abstract_members(Surface)

    def test_a_module_level_function_is_not_read_as_a_member(self) -> None:
        """A helper shown after a class must not be attributed to it.

        ``validate_crossing`` follows ``CrossingConsumer`` in the same block, and reading it
        as a member would report a member that does not exist — a false positive that would
        push someone to "fix" a document that was already correct.
        """
        documented = _documented_members(_doc_text(), "CrossingConsumer")
        assert "validate_crossing" not in documented
        assert "consume" in documented
