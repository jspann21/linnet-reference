"""Entry point for the downloadable Windows Media Manager and installer worker."""
import sys


if __name__ == "__main__":
    if len(sys.argv) > 1:
        from tools.studio.installer import main
        raise SystemExit(main())
    from tools.studio.media_app import launch
    launch()
