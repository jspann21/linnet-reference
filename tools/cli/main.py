"""Linnet command surface. Command parsing and dispatch."""
import argparse
import json
import os
import subprocess
import sys

def emit(value):
    print(json.dumps(value, indent=2))

def parser():
    cli = argparse.ArgumentParser(prog="linnet", description="Native open firmware for classic iPods")
    commands = cli.add_subparsers(dest="command", required=True)
    from tools.cli.studio_commands import register_primary
    register_primary(commands)
    from tools.cli.media_commands import register_media
    register_media(commands)
    from tools.cli.studio_commands import register_support
    register_support(commands)
    from tools.cli.device_commands import register_device
    register_device(commands)
    from tools.cli.studio_commands import register_report
    register_report(commands)
    return cli

def main():
    args = parser().parse_args()
    try:
        if os.name == "nt" and (args.command in ("build", "doctor", "simulator") or
                                (args.command == "device" and args.action == "sram-bootstrap" and args.sram_action == "build")):
            paths = {name: getattr(args, name, None) for name in ("system", "output", "tape")}
            from tools.studio.build import wsl_command
            completed = subprocess.run(
                wsl_command(sys.argv[1:], paths=paths), capture_output=True,
                text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
            if completed.stdout and sys.stdout is not None:
                sys.stdout.write(completed.stdout)
            if completed.stderr and sys.stderr is not None:
                sys.stderr.write(completed.stderr)
            return completed.returncode
        if args.command in ('music', 'video', 'photos'):
            from tools.cli.media_commands import run_media
            return run_media(args, emit)
        if args.command == 'device':
            from tools.cli.device_commands import run_device
            return run_device(args, emit)
        from tools.cli.studio_commands import run_studio
        return run_studio(args, emit)
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"linnet: {exc}", file=sys.stderr)
        return 1
