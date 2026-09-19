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

"""Tests for the extension registry.

The registry is the part of the package that decides whether a third-party backend is
*compatible*, so the tests here are mostly about what it refuses. A registry that
accepted anything would let a misconfigured deployment fail later, at a call site in a
different layer, where the traceback points at the wrong place.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import FunctionType

import pytest

from rsihybridagent.core import Receipt, ScenarioId, Substrate, SubstrateKind
from rsihybridagent.interlock.base import (
    Channel,
    Crossing,
    CrossingConsumer,
    CrossingProducer,
    InterlockPort,
)
from rsihybridagent.ledger.memory import MemoryLedger
from rsihybridagent.registry import (
    REQUIRED_BASE,
    ExtensionPoint,
    RegistryError,
    available,
    clear_local,
    describe,
    load,
    register,
    unregister,
)


@pytest.fixture(autouse=True)
def _clean() -> None:
    """Keep local registrations from leaking between tests."""
    clear_local()
    yield
    clear_local()


class _StubSubstrate(Substrate):
    """A minimal conforming substrate, used to prove the registry accepts one."""

    def kind(self) -> SubstrateKind:
        return SubstrateKind.DIGITAL

    def execute(self, request: Mapping[str, object], *, scenario: ScenarioId) -> tuple[Receipt, Mapping[str, object]]:
        return Receipt(value="r", scenario=scenario), {}

    def health(self, *, scenario: ScenarioId) -> Mapping[str, object]:
        return {"healthy": True}


def test_every_extension_point_names_a_required_base() -> None:
    """No group may be declared without a contract its members must satisfy.

    This is what makes the registry a compatibility check rather than a lookup table. A
    group with no base would accept a value that cannot be used, and the failure would
    surface later as an AttributeError inside the loop.
    """
    assert set(REQUIRED_BASE) == set(ExtensionPoint)
    for point, base in REQUIRED_BASE.items():
        assert isinstance(base, type), f"{point.value} does not name a class"


def test_a_conforming_implementation_is_accepted() -> None:
    """A registered instance that satisfies its base resolves."""
    register(ExtensionPoint.SUBSTRATE, "stub", _StubSubstrate())
    resolved = load(ExtensionPoint.SUBSTRATE, "stub")
    assert isinstance(resolved, _StubSubstrate)


def test_a_zero_argument_factory_is_accepted() -> None:
    """A callable returning a conforming instance resolves to the instance.

    Both shapes are accepted because a descriptor is naturally a value while a backend
    holding a live connection is naturally a factory.
    """
    register(ExtensionPoint.SUBSTRATE, "factory", lambda: _StubSubstrate())
    assert isinstance(load(ExtensionPoint.SUBSTRATE, "factory"), _StubSubstrate)


def test_a_value_that_satisfies_nothing_is_refused() -> None:
    """A plain value is refused, and the message says which contract it missed."""
    register(ExtensionPoint.SUBSTRATE, "wrong", object())
    with pytest.raises(RegistryError, match="Substrate"):
        load(ExtensionPoint.SUBSTRATE, "wrong")


def test_a_factory_returning_the_wrong_type_is_refused() -> None:
    """A factory whose product fails the contract is refused at resolution, not at use."""
    register(ExtensionPoint.SUBSTRATE, "bad_factory", lambda: 42)
    with pytest.raises(RegistryError, match="produced a int"):
        load(ExtensionPoint.SUBSTRATE, "bad_factory")


def test_a_missing_extension_explains_how_to_supply_one() -> None:
    """The error is the entry point's documentation, so it must say how to register.

    A missing backend is the most common wiring mistake, and the message a developer
    sees is the only place they will learn the group name.
    """
    with pytest.raises(RegistryError) as exc:
        load(ExtensionPoint.SUBSTRATE, "not-there")
    message = str(exc.value)
    assert "not-there" in message
    assert ExtensionPoint.SUBSTRATE.value in message
    assert "entry-points" in message


def test_an_empty_name_is_refused() -> None:
    """A nameless registration could never be selected, so it is rejected on creation."""
    with pytest.raises(RegistryError, match="must not be empty"):
        register(ExtensionPoint.SUBSTRATE, "", _StubSubstrate())


def test_unregistering_something_absent_is_not_an_error() -> None:
    """Removal is idempotent, so a cleanup path does not have to check first."""
    unregister(ExtensionPoint.SUBSTRATE, "never-registered")


def test_local_registrations_are_listed_and_removable() -> None:
    """``available`` reflects local registrations, and ``unregister`` drops one."""
    register(ExtensionPoint.SUBSTRATE, "one", _StubSubstrate())
    register(ExtensionPoint.SUBSTRATE, "two", _StubSubstrate())
    assert "one" in available(ExtensionPoint.SUBSTRATE)
    assert "two" in available(ExtensionPoint.SUBSTRATE)

    unregister(ExtensionPoint.SUBSTRATE, "one")
    assert "one" not in available(ExtensionPoint.SUBSTRATE)
    assert "two" in available(ExtensionPoint.SUBSTRATE)


def test_a_direct_reference_resolves_without_registration() -> None:
    """A ``module:attribute`` reference works with nothing registered at all.

    This is the escape hatch for a deployment that pins its own wiring, and for a test
    that wants a fake without touching the registry. The reference points at a zero-arg
    class in the package, which is the shape a real backend reference takes.
    """
    resolved = load(ExtensionPoint.LEDGER, "rsihybridagent.ledger.memory:MemoryLedger")
    assert isinstance(resolved, MemoryLedger)


def test_a_reference_that_does_not_satisfy_the_group_is_refused() -> None:
    """A real class from the wrong group is refused, not silently accepted.

    Pointing a group at a class that exists but implements a different abstraction is an
    easy wiring mistake, and one the registry can catch precisely because each group
    names the base its members must satisfy.
    """
    with pytest.raises(RegistryError, match="is not a Surface"):
        load(ExtensionPoint.SURFACE, "rsihybridagent.surfaces.memory:MemoryArtifactRepository")


def test_a_dotted_spec_without_a_colon_reports_the_format() -> None:
    """A colon-free dotted path is a malformed reference, not an unknown name.

    Reporting "no extension by that name" would send someone to hunt for a registration
    mistake when the actual problem is the reference's syntax.
    """
    with pytest.raises(RegistryError, match="has no attribute part"):
        load(ExtensionPoint.SUBSTRATE, "my_pkg.module")


def test_a_malformed_reference_is_refused() -> None:
    """A reference missing its attribute half is rejected with the expected form."""
    with pytest.raises(RegistryError, match="module:attribute"):
        load(ExtensionPoint.SUBSTRATE, "some.module:")


def test_an_unimportable_module_names_itself() -> None:
    """A bad module path reports the module, not a bare ImportError."""
    with pytest.raises(RegistryError, match="cannot import module"):
        load(ExtensionPoint.SUBSTRATE, "definitely_not_a_module:Thing")


def test_a_missing_attribute_names_itself() -> None:
    """A bad attribute reports the attribute and the module that lacks it."""
    with pytest.raises(RegistryError, match="no attribute"):
        load(ExtensionPoint.SUBSTRATE, "rsihybridagent.core:NotAThing")


def test_describe_names_the_contract_and_the_origin() -> None:
    """The listing states the required base and where each entry came from.

    Origin matters during a debugging session: a local registration shadowing an
    installed backend is the usual reason a change appears to have no effect.
    """
    register(ExtensionPoint.SUBSTRATE, "local_one", _StubSubstrate())
    lines = describe(ExtensionPoint.SUBSTRATE)
    assert "Substrate" in lines[0]
    assert any("local_one" in line and "local" in line for line in lines)


def test_describe_handles_an_empty_group() -> None:
    """An empty group is reported as empty rather than omitted.

    "The group exists and nothing is installed" is different information from "the group
    is not recognized", and a deployment debugging a missing backend needs the first.
    """
    lines = describe(ExtensionPoint.INTERLOCK)
    assert any("nothing installed" in line for line in lines)


def test_a_reference_to_a_class_needing_arguments_is_diagnosed() -> None:
    """A reference to a constructor that requires arguments is a RegistryError, not a TypeError.

    A class is callable, so this shape reaches the factory branch and used to fail with a
    bare ``TypeError`` from inside the registry. That traceback points at the registry
    instead of at the wiring mistake, and it never says the two accepted shapes are an
    instance or a zero-argument factory. Pointing a group at a real backend class that
    needs a connection is the most likely way to hit this.
    """
    with pytest.raises(RegistryError) as exc:
        load(ExtensionPoint.SUBSTRATE, "rsihybridagent.substrate.arithmetic:ArithmeticSubstrate")
    message = str(exc.value)
    assert "could not be called with no arguments" in message
    assert "zero-argument callable" in message
    assert "Substrate" in message


def test_interlock_port_is_a_method_not_a_property() -> None:
    """``InterlockPort.channel`` must be a plain method, for the reason the other points are.

    ``@property`` combined with ``@abstractmethod`` cannot be satisfied by a dataclass
    field of the same name: the field becomes a class attribute holding the descriptor,
    so the subclass stays abstract and raises at instantiation. The interlock point is
    registered like every other, so it has to follow the same rule.
    """
    for name in ("channel", "health"):
        assert isinstance(getattr(InterlockPort, name), FunctionType), (
            f"InterlockPort.{name} is not a plain method; a dataclass implementation cannot satisfy it"
        )
    assert isinstance(CrossingProducer.produce, FunctionType)
    assert isinstance(CrossingConsumer.consume, FunctionType)


def test_a_dataclass_interlock_port_can_be_instantiated() -> None:
    """A dataclass implementing the interlock port is constructible and resolves.

    This is the failure the rule above prevents, asserted directly rather than by
    inspecting descriptors: the subclass must be instantiable with its channel as a field.
    """

    @dataclass(frozen=True)
    class _Producer(CrossingProducer):
        _channel: Channel

        def channel(self) -> Channel:
            return self._channel

        def health(self, *, scenario: ScenarioId) -> Mapping[str, object]:
            return {"healthy": True}

        def produce(self, *, scenario: ScenarioId) -> tuple[Crossing, ...]:
            return ()

    register(ExtensionPoint.INTERLOCK, "producer", _Producer(Channel.SKILL_TRANSFER))
    resolved = load(ExtensionPoint.INTERLOCK, "producer")
    assert isinstance(resolved, CrossingProducer)
    assert resolved.channel() is Channel.SKILL_TRANSFER
