# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Historical replay (INV-006).

This package must never import persistence, tools.gateway, workers, or any
network client: it operates only on recorded event records. A test enforces
this import boundary.
"""
