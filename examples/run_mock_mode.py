#!/usr/bin/env python
"""
Example: Running Axon Aone with Angel One in Mock Mode
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from axon_aone.orchestration.main import main

if __name__ == "__main__":
    print("=" * 70)
    print("Axon Aone - Angel One Example (Mock Mode)")
    print("=" * 70)
    print()
    
    # Run in mock mode
    main(use_mock=True)
