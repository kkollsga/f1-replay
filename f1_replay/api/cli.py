"""
CLI for f1-replay.

Usage:
    f1-replay race 2024 monaco
    f1-replay race 2024 8 --port 8080
    f1-replay config --set-cache-dir /path/to/data
    f1-replay config --show
"""

import argparse
import sys


def cmd_race(args):
    """Launch race replay viewer."""
    from f1_replay import Manager

    manager = Manager(cache_dir=args.cache_dir)

    # Parse round (int or string)
    try:
        round_id = int(args.round)
    except ValueError:
        round_id = args.round

    manager.race(
        args.year,
        round_id,
        host=args.host,
        port=args.port,
        debug=not args.no_debug,
        force_update=args.force_update
    )


def cmd_config(args):
    """Show or set configuration."""
    from f1_replay.config import get_config, set_cache_dir, CONFIG_FILE

    if args.set_cache_dir:
        set_cache_dir(args.set_cache_dir)
        print(f"Cache directory set to: {args.set_cache_dir}")
        print(f"Saved to: {CONFIG_FILE}")
        return

    # Show current config
    config = get_config()
    print("f1-replay configuration:")
    print(f"  cache_dir: {config['cache_dir']}")
    print(f"  source:    {config['source']}")
    print(f"  config:    {config['config_file']}")


def cmd_server(args):
    """Run standalone API server."""
    from f1_replay.managers import DataLoader
    from f1_replay.api import create_app

    loader = DataLoader(cache_dir=args.cache_dir)
    app = create_app(loader)

    print(f"\n🚀 Starting F1 Race Viewer API on http://{args.host}:{args.port}")
    print(f"📁 Cache directory: {args.cache_dir}")
    app.run(host=args.host, port=args.port, debug=not args.no_debug)


def cmd_seasons(args):
    """List available seasons and races."""
    from f1_replay import Manager

    manager = Manager(cache_dir=args.cache_dir)
    seasons = manager.get_seasons()

    if seasons is None:
        print("Could not load seasons")
        return

    if args.year:
        # Show specific year
        season = manager.get_season(args.year)
        if season is None:
            print(f"Season {args.year} not found")
            return
        print(f"\n{args.year} Season ({len(season)} rounds):\n")
        for r in season:
            print(f"  {r.round_number:2d}. {r.name} ({r.circuit_name})")
    else:
        # Show all years
        years = sorted(seasons.keys())
        print(f"\nAvailable seasons: {', '.join(map(str, years))}")
        print("\nUse 'f1-replay seasons <year>' for race list")


def main():
    """Main CLI entry point."""
    from f1_replay.config import get_cache_dir

    parser = argparse.ArgumentParser(
        prog="f1-replay",
        description="Formula 1 Race Replay Viewer"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Common arguments
    cache_dir_default = get_cache_dir()

    # === race command ===
    race_parser = subparsers.add_parser("race", help="Launch race replay viewer")
    race_parser.add_argument("year", type=int, help="Season year (e.g., 2024)")
    race_parser.add_argument("round", help="Round number or event name (e.g., 8 or 'monaco')")
    race_parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    race_parser.add_argument("--port", "-p", type=int, default=5000, help="Port (default: 5000)")
    race_parser.add_argument("--no-debug", action="store_true", help="Disable debug mode")
    race_parser.add_argument("--force-update", "-f", action="store_true", help="Force reload from FastF1")
    race_parser.add_argument("--cache-dir", default=cache_dir_default, help=f"Cache directory (default: {cache_dir_default})")
    race_parser.set_defaults(func=cmd_race)

    # === config command ===
    config_parser = subparsers.add_parser("config", help="Show or set configuration")
    config_parser.add_argument("--set-cache-dir", metavar="PATH", help="Set global cache directory")
    config_parser.set_defaults(func=cmd_config)

    # === server command ===
    server_parser = subparsers.add_parser("server", help="Run standalone API server")
    server_parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    server_parser.add_argument("--port", "-p", type=int, default=5000, help="Port (default: 5000)")
    server_parser.add_argument("--no-debug", action="store_true", help="Disable debug mode")
    server_parser.add_argument("--cache-dir", default=cache_dir_default, help=f"Cache directory (default: {cache_dir_default})")
    server_parser.set_defaults(func=cmd_server)

    # === seasons command ===
    seasons_parser = subparsers.add_parser("seasons", help="List available seasons and races")
    seasons_parser.add_argument("year", type=int, nargs="?", help="Show races for specific year")
    seasons_parser.add_argument("--cache-dir", default=cache_dir_default, help=f"Cache directory (default: {cache_dir_default})")
    seasons_parser.set_defaults(func=cmd_seasons)

    # Parse and run
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
