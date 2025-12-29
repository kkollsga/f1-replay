"""
CLI entry point for F1 Replay Viewer Flask API.

Usage:
    python -m f1_replay.api.cli
    python -m f1_replay.api.cli --port 8080
    python -m f1_replay.api.cli --host 127.0.0.1 --port 5000
"""

import argparse
from f1_replay.data_loader import DataLoader
from f1_replay.api import create_app


def main():
    """Run Flask app from CLI."""
    parser = argparse.ArgumentParser(description='F1 Race Viewer API Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind (default: 5000)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--cache-dir', default='race_data', help='Cache directory (default: race_data)')

    args = parser.parse_args()

    # Create data loader
    loader = DataLoader(cache_dir=args.cache_dir)

    # Create Flask app
    app = create_app(loader)

    # Run
    print(f"\n🚀 Starting F1 Race Viewer on http://{args.host}:{args.port}")
    print(f"📁 Cache directory: {args.cache_dir}")
    print(f"🔗 API endpoints:")
    print(f"   - http://{args.host}:{args.port}/api/seasons")
    print(f"   - http://{args.host}:{args.port}/api/weekend/<year>/<round>")
    print(f"   - http://{args.host}:{args.port}/api/session/<year>/<round>/<session_type>")
    print(f"\nPress Ctrl+C to stop\n")

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
