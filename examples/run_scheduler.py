#!/usr/bin/env python
"""
Example: Running Axon Aone Scheduler
Runs automated trading during market hours
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from axon_aone.orchestration.main import run_scheduled

if __name__ == "__main__":
    print("=" * 70)
    print("Axon Aone - Scheduler Example (Mock Mode)")
    print("=" * 70)
    print()
    
    # Run scheduler in mock mode
    run_scheduled(use_mock=True)
