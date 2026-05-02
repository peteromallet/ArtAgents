#!/usr/bin/env python3
"""Compatibility launcher for the ArtAgents package entry point."""

from artagents.pipeline import main


if __name__ == "__main__":
    raise SystemExit(main())
