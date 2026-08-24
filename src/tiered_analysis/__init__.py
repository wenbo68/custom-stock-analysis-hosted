# -*- coding: utf-8 -*-
"""Tiered analysis (docs/tiered-analysis-design.md).

Standalone capability layered on top of DSA. This package must not import
from or modify the existing single-shot decision path (src/analyzer.py,
src/stock_analyzer.py, src/core/pipeline.py).
"""
