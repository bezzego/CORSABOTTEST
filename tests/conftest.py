"""
Test configuration and fixtures.

This file ensures the project root is on sys.path so tests can import the `src` package
when pytest is executed from the repository root.
"""
import sys
from pathlib import Path

# Add project root to sys.path (two levels up from tests/)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


