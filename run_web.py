#!/usr/bin/env python
"""
Axon Trading - Web Server Launcher

This script starts the web-based trading interface with real-time order management.

Usage:
    python run_web.py                    # Run on localhost:5000 (HTTP)
    python run_web.py --host 0.0.0.0    # Accept connections from any host
    python run_web.py --port 8080       # Run on custom port
    python run_web.py --debug           # Enable debug mode
    python run_web.py --https           # Enable HTTPS with self-signed cert
    python run_web.py --https --certfile cert.pem --keyfile key.pem

Requirements:
    - Flask
    - Flask-SocketIO
    - python-socketio
    - python-engineio
    - eventlet

Access the web interface at: http://localhost:5000
"""

import os
import sys
import logging
import argparse

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from axon_aone.interfaces.web.app import run_web_server


def print_banner():
    """Print application banner."""
    banner = """
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║     📈 Axon Trading - Web Based Terminal 📈              ║
    ║                                                               ║
    ║              Real-time Trading & Order Management              ║
    ║                      v1.0 Web Edition                          ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """
    print(banner)


def print_help():
    """Print help message."""
    help_text = """
    
    ╔═══════════════════════════════════════════════════════════════╗
    ║              AXON TRADING - WEB INTERFACE                 ║
    ╚═══════════════════════════════════════════════════════════════╝
    
    USAGE:
        python run_web.py [OPTIONS]
    
    OPTIONS:
        --host HOST             Host to bind to (default: 0.0.0.0)
        --port PORT             Port to listen on (default: 5000)
        --debug                 Enable debug mode
        --https                 Enable HTTPS (TLS). Uses self-signed cert
        --certfile PATH         TLS certificate file (PEM format)
        --keyfile PATH          TLS private key file (PEM format)
        -h, --help             Show this help message
    
    EXAMPLES:
        # Start on localhost:5000 (production)
        python run_web.py --host 127.0.0.1
        
        # Start on all interfaces:8080 (development)
        python run_web.py --port 8080 --debug
        
        # Start with debug mode for development
        python run_web.py --debug

        # Start with HTTPS using an auto-generated self-signed cert
        python run_web.py --https

        # Start with HTTPS using your own certificate and key
        python run_web.py --https --certfile cert.pem --keyfile key.pem
    
    ACCESS:
        Once running, open your browser and navigate to:
        
        http(s)://localhost:5000       (if using --host 127.0.0.1)
        http(s)://<your-ip>:5000       (if using --host 0.0.0.0)
    
    FEATURES:
        ✓ Place mock and live trades
        ✓ Real-time order monitoring
        ✓ Position tracking
        ✓ Portfolio dashboard
        ✓ Market status indicator
        ✓ WebSocket real-time updates
        ✓ Responsive web interface
    
    TRADE MODES:
        - Mock Mode (Paper Trading): Simulates trades without actual capital
        - Live Mode: Executes real trades with Angel One broker
    
    ═══════════════════════════════════════════════════════════════
    """
    print(help_text)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Axon Trading - Web Based Terminal',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=True
    )
    
    parser.add_argument(
        '--host',
        type=str,
        default='0.0.0.0',
        help='Host to bind to (default: 0.0.0.0)'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=5000,
        help='Port to listen on (default: 5000)'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode'
    )

    parser.add_argument(
        '--https',
        action='store_true',
        help='Enable HTTPS/TLS (uses self-signed cert if no cert/key provided)'
    )

    parser.add_argument(
        '--certfile',
        type=str,
        default=None,
        help='Path to TLS certificate file (PEM format) when using --https'
    )

    parser.add_argument(
        '--keyfile',
        type=str,
        default=None,
        help='Path to TLS private key file (PEM format) when using --https'
    )
    
    args = parser.parse_args()
    
    print_banner()
    
    if args.debug:
        print("🔧 Debug mode ENABLED")
        print()
    
    scheme = "https" if args.https else "http"
    print(f"Starting Web Server on {scheme}://{args.host}:{args.port}")
    print()
    print(f"📍 Access the interface at:")
    if args.host == '0.0.0.0':
        print(f"   - {scheme}://localhost:{args.port}")
        print(f"   - {scheme}://<your-machine-ip>:{args.port}")
    else:
        print(f"   - {scheme}://{args.host}:{args.port}")
    print()
    print("⚡ Features available:")
    print("   ✓ Mock Trading (Paper)")
    print("   ✓ Live Trading (Angel One)")
    print("   ✓ Real-time Order Updates")
    print("   ✓ Position Tracking")
    print("   ✓ Portfolio Dashboard")
    print()
    print("Press Ctrl+C to stop the server")
    print("─" * 65)
    print()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        run_web_server(
            host=args.host,
            port=args.port,
            debug=args.debug,
            use_https=args.https,
            certfile=args.certfile,
            keyfile=args.keyfile,
        )
    except KeyboardInterrupt:
        print("\n\n✓ Server stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
