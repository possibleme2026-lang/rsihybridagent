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

"""Command line entry point.

The commands here are deliberately few. Anything that needs a running substrate or
a training backend belongs to a deployment, not to the framework's CLI.
"""

from __future__ import annotations

import argparse
import sys

from rsihybridagent import __version__
from rsihybridagent.interlock.base import Channel


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="rsihybrid",
        description="Recursive self-improvement for hybrid agents.",
    )
    parser.add_argument("--version", action="version", version=f"rsihybridagent {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("channels", help="List the interlock channels and their directions.")

    return parser


def describe_channels() -> str:
    """Render the four interlock channels as a fixed-width table."""
    lines = [
        f"{'channel':<26}{'source':<10}{'target':<10}{'surface'}",
        "-" * 60,
    ]
    for channel in Channel:
        lines.append(f"{channel.value:<26}{channel.source.value:<10}{channel.target.value:<10}{channel.surface.value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "channels":
        print(describe_channels())
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
