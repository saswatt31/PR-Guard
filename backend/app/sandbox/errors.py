"""Sandbox-specific exceptions."""

from __future__ import annotations


class SandboxError(RuntimeError):
    """Base class for sandbox failures."""


class SandboxUnavailable(SandboxError):
    """The selected sandbox backend cannot be reached."""


class SandboxPolicyError(SandboxError):
    """A command or configuration would violate the sandbox policy."""
