"""Shared W&B Weave configuration for tracing and evaluation."""

import os

import weave
from dotenv import load_dotenv

load_dotenv()

# Format: "team/project" or just "project" (uses your default W&B entity)
WEAVE_PROJECT = os.getenv("WEAVE_PROJECT", "relatability-engine")


def init_weave():
    """Initialize Weave tracing. Call once at app startup."""
    return weave.init(WEAVE_PROJECT)
