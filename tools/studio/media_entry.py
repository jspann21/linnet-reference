"""Entry point for the downloadable Windows Media Manager and installer worker."""
import sys


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == '--media-read':
        from tools.studio.media_reader import main
        raise SystemExit(main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == '--encode-ipvf':
        from tools.content.ipvf_encode import main
        raise SystemExit(main(sys.argv[2:]))
    if len(sys.argv) > 1:
        from tools.studio.installer import main
        raise SystemExit(main())
    from tools.studio.media_app import launch
    launch()
