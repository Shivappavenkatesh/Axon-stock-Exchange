#!/usr/bin/env python
"""
Example: Running Axon Aone with Angel One Smart API (Live Mode)

IMPORTANT: Set your Angel One credentials before running!

Environment variables:
    export ANGEL_ONE_API_KEY=your_api_key       # From SmartAPI developer portal
    export ANGEL_ONE_CLIENT_ID=your_client_id  # Your Angel One User ID (e.g., D12345)
    export ANGEL_ONE_PIN=your_pin              # Your 4-digit trading PIN
    export ANGEL_ONE_TOTP_SECRET=your_totp_secret  # TOTP secret from Angel One app
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from axon_aone.orchestration.main import main

if __name__ == "__main__":
    print("=" * 70)
    print("Axon Aone - Angel One Smart API Example (Live Mode)")
    print("=" * 70)
    print()
    
    # Check if credentials are set
    api_key = os.getenv("ANGEL_ONE_API_KEY")
    client_id = os.getenv("ANGEL_ONE_CLIENT_ID")
    pin = os.getenv("ANGEL_ONE_PIN")
    totp_secret = os.getenv("ANGEL_ONE_TOTP_SECRET")
    
    if not all([api_key, client_id, pin, totp_secret]):
        print("ERROR: Angel One credentials not fully configured!")
        print()
        print("Set your credentials first:")
        print("  export ANGEL_ONE_API_KEY=your_api_key")
        print("  export ANGEL_ONE_CLIENT_ID=your_user_id   # e.g., D12345")
        print("  export ANGEL_ONE_PIN=your_mpin           # 4-digit PIN")
        print("  export ANGEL_ONE_TOTP_SECRET=your_totp   # From Angel One app TOTP setup")
        print()
        print("To get TOTP Secret:")
        print("  1. Open Angel One Trading app")
        print("  2. Go to Profile > Settings > TOTP")
        print("  3. Enable TOTP (or Reset if already enabled)")
        print("  4. Copy the secret key shown (or scan QR into authenticator)")
        print()
        sys.exit(1)
    
    # Run in live mode
    main(use_mock=False)
