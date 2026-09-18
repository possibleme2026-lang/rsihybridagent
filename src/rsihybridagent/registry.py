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

"""Extension registry: how a third-party package plugs in without forking.

:mod:`rsihybridagent.core` says what an implementation must *do*. This module says
how one is *found*. Both are required for an interface to be open: an interface
nobody can discover is not an open interface, it is just an abstract class.

Three ways to supply an implementation, in increasing order of permanence:

- ``load(point, "my_pkg.module:MySubstrate")`` — a direct reference. For a script,
  a test, or a deployment that pins its own wiring.
- ``register(point, name, value)`` — in-process, scoped to this interpreter. For a
  test that wants a fake.
- an installed entry point — for a distributed package. This is the only one that
  survives into someone else's environment, which is what makes it the mechanism
  that matters.

**Why entry points rather than scanning a plugin directory.** A directory scan
imports code in order to learn what is there, so discovery has side effects and its
result depends on filesystem order. Entry points are declared in packaging metadata,
so listing them imports nothing and the set is deterministic.

A group's value is the implementation itself or a zero-argument callable returning
one — the same contract reef uses, adopted so that a backend written for either
project has the same shape. Both are accepted because a descriptor is naturally a
value while a backend holding a connection is naturally a factory.

**Selection is by name, and a missing name is an error rather than a fallback.** A
silent default would let a deployment believe it was running a physical substrate
while it was running a stub, which is the same class of failure the evidence ledger
exists to prevent.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from importlib import import_module
from importlib.metadata import EntryPoints, entry_points
from typing import cast

from rsihybridagent.core import Substrate, Surface
from rsihybridagent.interlock.base import InterlockPort
from rsihybridagent.ledger.base import AdmissionPolicy, Ledger
from rsihybridagent.loop import Recipe, Verifier


class ExtensionPoint(StrEnum):
    """One registration group.

    The value is the group name as it appears in packaging metadata, so a
    third-party package declares its backend with no import of this module:

    .. code-block:: toml

        [project.entry-points."rsihybridagent.substrates"]
        libero = "my_pkg.substrates:LiberoSubstrate"
    """

    SUBSTRATE = "rsihybridagent.substrates"
    SURFACE = "rsihybridagent.surfaces"
    RECIPE = "rsihybridagent.recipes"
    VERIFIER = "rsihybridagent.verifiers"
    POLICY = "rsihybridagent.policies"
    LEDGER = "rsihybridagent.ledgers"
    INTERLOCK = "rsihybridagent.interlock"


#: The contract each group's value must satisfy. This mapping is what makes the
#: registry a *compatibility* check rather than a lookup table: a group cannot be
#: declared without naming the abstraction its members must implement.
REQUIRED_BASE: Mapping[ExtensionPoint, type] = {
    ExtensionPoint.SUBSTRATE: Substrate,
    ExtensionPoint.SURFACE: Surface,
    ExtensionPoint.RECIPE: Recipe,
    ExtensionPoint.VERIFIER: Verifier,
    ExtensionPoint.POLICY: AdmissionPolicy,
    ExtensionPoint.LEDGER: Ledger,
    ExtensionPoint.INTERLOCK: InterlockPort,
}


class RegistryError(Exception):
    """An extension is missing, ambiguous, or does not satisfy its contract."""


_LOCAL: dict[ExtensionPoint, dict[str, object]] = {}


def register(point: ExtensionPoint, name: str, value: object) -> None:
    """Supply an implementation for this interpreter only.

    A local registration shadows an installed one of the same name, so a test can
    replace a real backend with a fake without uninstalling anything.
    """
    if not name:
        raise RegistryError("an extension name must not be empty")
    _LOCAL.setdefault(point, {})[name] = value


def unregister(point: ExtensionPoint, name: str) -> None:
    """Remove a local registration. Removing one that is absent is not an error."""
    _LOCAL.get(point, {}).pop(name, None)


def clear_local(point: ExtensionPoint | None = None) -> None:
    """Drop local registrations, for test isolation between cases."""
    if point is None:
        _LOCAL.clear()
    else:
        _LOCAL.pop(point, None)


def available(point: ExtensionPoint) -> tuple[str, ...]:
    """Names resolvable for a group, sorted. Local names shadow, never duplicate."""
    names = {entry.name for entry in _installed(point)}
    names |= set(_LOCAL.get(point, {}))
    return tuple(sorted(names))


def load(point: ExtensionPoint, spec: str) -> object:
    """Resolve, materialize, and conformance-check one implementation.

    ``spec`` is either a registered name or a ``module:attribute`` reference. The
    returned object is guaranteed to be an instance of the group's required base;
    a value that is not is refused here rather than failing later at a call site,
    where the traceback would point at the wrong layer.
    """
    raw = _resolve(point, spec)
    required = REQUIRED_BASE[point]
    if isinstance(raw, required):
        return raw
    if callable(raw):
        produced = cast(Callable[[], object], raw)()
        if isinstance(produced, required):
            return produced
        raise RegistryError(
            f"extension {spec!r} in {point.value} produced a {type(produced).__name__}, "
            f"which is not a {required.__name__}"
        )
    raise RegistryError(
        f"extension {spec!r} in {point.value} is a {type(raw).__name__}, which is neither "
        f"a {required.__name__} nor a zero-argument callable returning one"
    )


def describe(point: ExtensionPoint) -> tuple[str, ...]:
    """Human-readable lines for one group, for a CLI or a startup log."""
    required = REQUIRED_BASE[point]
    lines = [f"{point.value}  (must implement {required.__name__})"]
    names = available(point)
    if not names:
        lines.append("  (nothing installed)")
    for name in names:
        origin = "local" if name in _LOCAL.get(point, {}) else "entry point"
        lines.append(f"  {name}  [{origin}]")
    return tuple(lines)


def _installed(point: ExtensionPoint) -> EntryPoints:
    """Entry points declared for a group, importing nothing."""
    return entry_points(group=point.value)


def _resolve(point: ExtensionPoint, spec: str) -> object:
    """Find one implementation, preferring a local registration over an installed one.

    A dotted spec with no colon is treated as a malformed reference rather than as an
    unknown name. ``my_pkg.module`` looks like a reference and is the shape someone
    reaches for when they mean one, so reporting "no extension by that name" would send
    them to look for a registration mistake that does not exist. A registered name is
    conventionally a bare identifier, which is what distinguishes the two.
    """
    if ":" in spec:
        return _import_reference(spec)
    if spec in _LOCAL.get(point, {}):
        return _LOCAL[point][spec]
    if _looks_like_reference(spec):
        raise RegistryError(
            f"reference {spec!r} has no attribute part; write it as '{spec}:ClassName'. "
            f"If {spec!r} was meant as a registered name, note that a name is a bare "
            f"identifier, not a dotted path."
        )
    matches = tuple(entry for entry in _installed(point) if entry.name == spec)
    if not matches:
        raise RegistryError(_missing_message(point, spec))
    if len(matches) > 1:
        origins = ", ".join(sorted(entry.value for entry in matches))
        raise RegistryError(
            f"extension {spec!r} in {point.value} is ambiguous: {len(matches)} providers "
            f"declare it ({origins}); uninstall one or reference it as 'module:attribute'"
        )
    return matches[0].load()


def _looks_like_reference(spec: str) -> bool:
    """Whether a colon-free spec is shaped like a dotted module path."""
    return bool(spec) and "." in spec and all(part.isidentifier() for part in spec.split("."))


def _import_reference(spec: str) -> object:
    """Import a ``module:attribute`` reference, reporting which half failed."""
    module_name, _, attribute = spec.partition(":")
    if not module_name or not attribute:
        raise RegistryError(f"reference {spec!r} must be written as 'module:attribute'")
    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise RegistryError(f"cannot import module {module_name!r} for reference {spec!r}: {exc}") from exc
    try:
        return getattr(module, attribute)
    except AttributeError as exc:
        raise RegistryError(f"module {module_name!r} has no attribute {attribute!r}") from exc


def _missing_message(point: ExtensionPoint, spec: str) -> str:
    """Explain the absence *and* how to fix it, since this error is the entry point's docs."""
    known = available(point)
    listing = ", ".join(known) if known else "nothing installed"
    return (
        f"no extension named {spec!r} in {point.value}; known: {listing}. "
        f"A package supplies one by declaring it under "
        f'[project.entry-points."{point.value}"] in its own pyproject.toml, '
        f"or this interpreter can register it with register()."
    )
