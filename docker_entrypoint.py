#!/usr/bin/env python3
"""
Axon Aone - Docker Entrypoint Script
Handles both mock and live trading modes for containerized deployment
"""

import os
import sys

# Ensure src is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def main():
    """Main entry point for Docker container."""
    # Determine if running in mock mode
    # Can be set via MOCK_MODE=true or --mock argument
    mock_mode = os.environ.get('MOCK_MODE', 'false').lower() == 'true'
    
    # Import after path is set
    from axon_aone.main import run_scheduled
    
    # Run scheduled trading
    run_scheduled(use_mock=mock_mode)


if __name__ == '__main__':
    main()
