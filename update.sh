#!/usr/bin/env bash
# Refresh the database now: full Criterion catalog walk + OMDb lookups
uv run movie-brain sync --full
