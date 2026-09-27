"""Linnet command surface. Command parsing and dispatch."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from tools.inspect.image import inspect, verify_release
from tools.link.music import ACTIONS as MUSIC_ACTIONS
from tools.studio.build import ROOT, TARGETS, build, target_id, toolchain

def emit(value):
    print(json.dumps(value, indent=2))

def _source_output_arguments(entry):
    entry.add_argument('--source', type=Path, required=True)
    entry.add_argument('--output', type=Path, required=True)


def _publication_arguments(entry, drive_help=None):
    entry.add_argument('--disk-number', type=int, required=True)
    entry.add_argument('--disk-serial', required=True)
    entry.add_argument('--volume-serial', required=True)
    entry.add_argument('--drive', help=drive_help)


def _record_arguments(entry):
    entry.add_argument('--mount', type=Path, required=True)
    entry.add_argument('--disk-serial', required=True)
    entry.add_argument('--disk-bytes', type=int, required=True)
    entry.add_argument('--confirmed-build', required=True)


def parser():
    cli = argparse.ArgumentParser(prog="linnet", description="Native open firmware for classic iPods")
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("media", help="Open the desktop iPod media manager")
    installer = commands.add_parser("installer", help="Inspect, install, or restore Linnet without erasing media")
    installer_actions = installer.add_subparsers(dest="installer_action", required=True)
    for action in ("inspect", "install", "restore"):
        entry = installer_actions.add_parser(action)
        entry.add_argument("--mount", type=Path, required=True)
        if action == "install":
            entry.add_argument("--build", choices=("user", "dev"), default="user",
                               help="OS build to install (default: user)")
            entry.add_argument("--method", choices=("rockbox-loader", "native-preserve", "native-selector"),
                               help="boot installation method (default: recommended detected method)")
    compile_ = commands.add_parser("build")
    compile_.add_argument("--target", default="photo4g-p98", type=target_id)
    compile_.add_argument("--profile", choices=("release", "dev", "trace"), required=True)
    compile_.add_argument("--verify", action="store_true")
    compile_.add_argument("--kind", choices=("os", "boot"), default="os")
    compile_.add_argument("--probe", choices=("frame", "crash", "hang"), default="frame")
    compile_.add_argument("--device-serial", default="")
    compile_.add_argument("--boot-selector", choices=("none", "rockbox"), default="none")
    compile_.add_argument("--system", type=Path, help="system.toml configuration")
    ui=commands.add_parser("ui").add_subparsers(dest="action",required=True)
    ui_compile=ui.add_parser("compile")
    ui_compile.add_argument("--output",type=Path,default=Path('out/ui'))
    ui_compile.add_argument("--system",type=Path)
    simulator=commands.add_parser("simulator")
    simulator.add_argument("--output",type=Path,default=Path('out/simulator'))
    simulator.add_argument("--system",type=Path)
    simulator.add_argument("--target",choices=sorted(TARGETS))
    simulator.add_argument("--all-scenes",action="store_true")
    simulator.add_argument("--tape",type=Path,help="JSON list of native input events")
    simulator.add_argument("--boot-menu",action="store_true",help="Render the native 320-pixel Boot chooser")
    music=commands.add_parser('music').add_subparsers(dest='action',required=True)
    music_compile=music.add_parser('compile')
    _source_output_arguments(music_compile)
    music_compile.add_argument('--target', choices=sorted(TARGETS), help='Prepare artwork for this display')
    music_compile.add_argument('--ffprobe',help='Optional executable for compressed-source metadata')
    music_compile.add_argument('--device-root',type=Path,help='Index existing files on this mounted iPod without copying audio')
    music_compile.add_argument('--include-root',type=Path,action='append',help='Limit an existing-device import to this root (repeatable)')
    music_compile.add_argument('--cache-path',type=Path,help='Reuse an existing music metadata cache outside the iPod')
    music_compile.add_argument('--verification',choices=('metadata','full'),help='Existing music defaults to fast metadata checks; full reads complete audio files')
    music_compile.add_argument('--refresh-metadata',action='store_true',help='Ignore cached metadata for this import')
    music_check=music.add_parser('inspect')
    music_check.add_argument('database',type=Path)
    music_publish=music.add_parser('publish',help='Publish verified staging to an explicitly identified mounted USB iPod')
    music_publish.add_argument('--stage',type=Path,required=True)
    _publication_arguments(music_publish, drive_help='Optional expected Windows drive letter')
    video=commands.add_parser('video').add_subparsers(dest='action',required=True)
    video_compile=video.add_parser('compile')
    _source_output_arguments(video_compile)
    video_compile.add_argument('--target',default='photo4g-p98',type=target_id)
    video_compile.add_argument('--fps',type=int,choices=range(4,31),help='Defaults to the target video frame rate')
    video_compile.add_argument('--ffmpeg')
    video_compile.add_argument('--ffprobe')
    video_inspect=video.add_parser('inspect')
    video_inspect.add_argument('package',type=Path)
    video_inspect.add_argument('--target', type=target_id, help='Required for native MP4 validation')
    video_publish=video.add_parser('publish')
    video_publish.add_argument('--package',type=Path,required=True)
    _publication_arguments(video_publish)
    video_publish.add_argument('--library-key',help='Stable source-relative identity for a video in the browsable library')
    video_publish.add_argument('--title',help='Video library display title')
    photos=commands.add_parser('photos').add_subparsers(dest='action',required=True)
    photo_compile=photos.add_parser('compile')
    _source_output_arguments(photo_compile)
    photo_compile.add_argument('--target',default='photo4g-p98',type=target_id)
    photo_compile.add_argument('--max-dimension',type=int,default=640,
        help='Largest prepared zoom dimension (default: 640); originals are unchanged')
    photo_inspect=photos.add_parser('inspect')
    photo_inspect.add_argument('package',type=Path)
    photo_publish=photos.add_parser('publish')
    photo_publish.add_argument('--package',type=Path,required=True)
    _publication_arguments(photo_publish)
    read = commands.add_parser("inspect")
    read.add_argument("image", type=Path)
    release = commands.add_parser("release").add_subparsers(dest="action", required=True).add_parser("verify")
    release.add_argument("image", type=Path)
    release.add_argument("--symbols", type=Path, required=True)
    storage=commands.add_parser("storage").add_subparsers(dest="action",required=True)
    package=storage.add_parser("package")
    package.add_argument("--image",type=Path,required=True)
    package.add_argument("--output",type=Path,required=True)
    provision=storage.add_parser("provision")
    provision.add_argument("--package",type=Path,required=True)
    provision.add_argument("--mount",type=Path,required=True)
    provision.add_argument("--serial",required=True)
    theme_provision=storage.add_parser("theme-provision",help="Add optional theme selection records to an identified Disk Mode installation")
    _record_arguments(theme_provision)
    device = commands.add_parser("device").add_subparsers(dest="action", required=True)
    retail = device.add_parser("detect-retail", help="Identify a mounted RetailOS iPod and its Linnet target")
    retail.add_argument("--mount", type=Path, required=True)
    retail.add_argument("--output", type=Path)
    info = device.add_parser("info")
    info.add_argument("--port")
    for action, help_text in (
            ('media-info', None),
            ('ui-state', None),
            ('startup-timing', 'Read retained development startup stage timings'),
            ('video-startup-timing', 'Read video startup latency and dropped display frames'),
            ('boot-timeline', 'Read native Boot and OS initialization timings')):
        options = {'help': help_text} if help_text else {}
        entry = device.add_parser(action, **options)
        entry.add_argument('--port', required=True)
    for action in MUSIC_ACTIONS:
        entry=device.add_parser(action)
        entry.add_argument('--port',required=True)
        if action in ('player-open','video-open'):entry.add_argument('--path',required=True)
        if action=='player-seek':entry.add_argument('--sample',type=int,required=True)
    history=device.add_parser("prepare-update-history",help="Add optional rollback history records to an identified Disk Mode installation")
    _record_arguments(history)
    native=device.add_parser("native-install")
    native.add_argument("--package",type=Path,required=True)
    native.add_argument("--package-sha256",required=True)
    native.add_argument("--port",required=True)
    native_status=device.add_parser("native-status")
    native_status.add_argument("--port",required=True)
    storage_cycle=device.add_parser("storage-cycle")
    storage_cycle.add_argument("--image",type=Path,required=True)
    storage_cycle.add_argument("--scenario",type=Path,required=True)
    storage_cycle.add_argument("--port",required=True)
    update_cycle=device.add_parser("update-cycle")
    update_cycle.add_argument("--image",type=Path,required=True)
    update_cycle.add_argument("--crash-image",type=Path,required=True)
    update_cycle.add_argument("--port",required=True)
    sync_cycle=device.add_parser("storage-sync-cycle")
    sync_cycle.add_argument("--image",type=Path,required=True)
    sync_cycle.add_argument("--port",required=True)
    sync_cycle.add_argument("--disk-number",type=int,required=True)
    sync_cycle.add_argument("--plan",type=Path,required=True)
    sync_cycle.add_argument("--plan-sha256",required=True)
    for action in ("storage-info","storage-recover","storage-fault","install"):
        entry=device.add_parser(action)
        entry.add_argument("--port",required=True)
        if action=="storage-fault":entry.add_argument("--mode",type=int,choices=range(1,6),required=True)
        if action=="install":entry.add_argument("--image",type=Path,required=True)
    eject = device.add_parser("eject", help="Safely eject an explicitly identified Windows USB iPod disk")
    eject.add_argument("--disk-number", type=int, required=True)
    eject.add_argument("--expected-serial", help="Required for ordinary eject; reboot uses the reviewed plan identity")
    eject.add_argument("--wait-link", action="store_true")
    eject.add_argument("--link-serial", help="Required with --wait-link")
    eject.add_argument("--reboot", action="store_true", help="Refresh the exact installed Boot directory before eject and verify restart")
    eject.add_argument("--plan", type=Path)
    eject.add_argument("--plan-sha256")
    eject.add_argument("--allow-uac", action="store_true", help="Allow normal Windows consent for the reviewed directory refresh; requires --reboot")
    refresh_session = device.add_parser("refresh-session", help="Manage a finite, plan-bound elevated restart session")
    refresh_actions = refresh_session.add_subparsers(dest="session_action", required=True)
    refresh_prepare = refresh_actions.add_parser("prepare")
    refresh_prepare.add_argument("--plan", type=Path, required=True)
    refresh_prepare.add_argument("--plan-sha256", required=True)
    refresh_prepare.add_argument("--hours", type=int, default=8)
    refresh_prepare.add_argument("--install-reviewed-boot", action="store_true", help="Authorize only the exact reviewed Boot image for this finite session")
    refresh_prepare.add_argument("--usb-serial", help="Approve bounded USB tracing and restart of this device on its pinned port")
    for action in ("trace-start", "trace-stop", "usb-restart", "usb-cycle"):
        refresh_actions.add_parser(action)
    refresh_start = refresh_actions.add_parser("start")
    refresh_start.add_argument("--prepared", type=Path, required=True)
    refresh_start.add_argument("--allow-uac", action="store_true")
    refresh_actions.add_parser("status")
    refresh_actions.add_parser("stop")
    refresh_install=refresh_actions.add_parser("install")
    refresh_install.add_argument("--disk-number",type=int,required=True)
    refresh_verify=refresh_actions.add_parser("verify",help="Read and verify the reviewed firmware without writing")
    refresh_verify.add_argument("--disk-number",type=int,required=True)
    cycle = device.add_parser("cycle")
    cycle.add_argument("--image", type=Path, required=True)
    cycle.add_argument("--scenario", type=Path, required=True)
    cycle.add_argument("--port")
    cycle.add_argument("--resume-run", type=Path, help="Resume an interrupted run using validated healthy-cycle evidence")
    cycle.add_argument("--crash-image", type=Path, required=True)
    cycle.add_argument("--hang-image", type=Path, required=True)
    cycle.add_argument("--release-image", type=Path, required=True)
    cycle.add_argument("--release-symbols", type=Path, required=True)
    platform = device.add_parser("platform-cycle")
    platform.add_argument("--image", type=Path, required=True)
    platform.add_argument("--scenario", type=Path, required=True)
    platform.add_argument("--port", required=True)
    reboot = device.add_parser("reboot")
    reboot.add_argument("--mode", choices=("os", "boot", "disk", "persistent"), required=True)
    reboot.add_argument("--port", required=True)
    ram = device.add_parser("boot")
    ram.add_argument("--mode", choices=("ram",), default="ram")
    ram.add_argument("--image", type=Path, required=True)
    ram.add_argument("--port", required=True)
    sram = device.add_parser("sram-bootstrap", help="Build and load the Classic's temporary Linnet Link monitor")
    sram_actions = sram.add_subparsers(dest="sram_action", required=True)
    sram_build = sram_actions.add_parser("build")
    sram_build.add_argument("--device-serial", required=True)
    sram_prepare = sram_actions.add_parser("prepare")
    sram_prepare.add_argument("--mount", type=Path, required=True)
    sram_update = sram_actions.add_parser("update", help="Upload and RAM-boot the current monitor through Linnet Link")
    sram_update.add_argument("--prepared", type=Path, required=True)
    sram_backup = sram_actions.add_parser("backup-nor", help="Read and independently verify the Classic's original boot flash")
    sram_backup.add_argument("--prepared", type=Path, required=True)
    sram_backup.add_argument("--output", type=Path, required=True)
    sram_nor_prepare = sram_actions.add_parser("prepare-nor", help="Authenticate a device-bound persistent monitor image")
    sram_nor_prepare.add_argument("--prepared", type=Path, required=True)
    sram_nor_prepare.add_argument("--backup", type=Path, required=True)
    sram_nor_prepare.add_argument("--output", type=Path, required=True)
    sram_nor_prepare.add_argument("--boot-image", type=Path, help="Include the verified native Boot stage in the existing NOR slot")
    sram_apple = sram_actions.add_parser("preserve-apple", help="Publish the verified original Apple loader for MENU-at-boot fallback")
    sram_apple.add_argument("--prepared", type=Path, required=True)
    sram_apple.add_argument("--backup", type=Path, required=True)
    sram_apple.add_argument("--mount", type=Path, required=True)
    sram_nor_install = sram_actions.add_parser("install-nor", help="Install the verified monitor in the original NOR boot slot and reboot")
    sram_nor_install.add_argument("--prepared", type=Path, required=True)
    sram_nor_install.add_argument("--plan-sha256", required=True)
    sram_diagnose = sram_actions.add_parser("diagnose", help="Read Classic board and disk diagnostics through Linnet Link")
    sram_diagnose.add_argument("--prepared", type=Path, required=True)
    sram_diagnose.add_argument("--display", action="store_true", help="Initialize the supported panel and send color bars")
    sram_load = sram_actions.add_parser("load")
    sram_load.add_argument("--prepared", type=Path, required=True)
    sram_load.add_argument("--wait-seconds", type=int, default=0)
    sram_load.add_argument("--after-reset", action="store_true", help="Wait for the current DFU interface to disappear before opening its replacement")
    sram_load.add_argument("--inspect-only", action="store_true", help="Read retained diagnostics and leave the device in DFU")
    sram_load.add_argument("--probe", choices=("identity", "memory", "storage"), help="Run a board probe and return to DFU")
    bootstrap = device.add_parser("bootstrap")
    bootstrap.add_argument("--mount", type=Path, required=True)
    bootstrap.add_argument("--image", type=Path, required=True)
    bootstrap.add_argument("--envelope", type=Path, required=True)
    bootstrap.add_argument("--expected-original-sha", required=True)
    restore = device.add_parser("restore")
    restore.add_argument("--mount", type=Path, required=True)
    bootstrap_status = device.add_parser("bootstrap-status")
    bootstrap_status.add_argument("--mount", type=Path, required=True)
    report = commands.add_parser("report")
    report.add_argument("run_id")
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
        if args.command == "doctor":
            emit(dict(toolchain=toolchain(), python=sys.version.split()[0],
                      supported_targets=sorted(target for target, spec in TARGETS.items() if spec.get('build_enabled', True)),
                      bringup_targets={target: spec['bringup_blocker'] for target, spec in TARGETS.items() if not spec.get('build_enabled', True)}))
        elif args.command == "media":
            from tools.studio.media_app import launch
            launch()
        elif args.command == "installer":
            from tools.studio.installer import assess, identity_for_mount, install, restore
            identity = identity_for_mount(args.mount)
            emit(assess(identity) if args.installer_action == "inspect" else
                 install(identity, progress=lambda message: print(message, file=sys.stderr), build=args.build,
                         installation_method=args.method)
                 if args.installer_action == "install" else restore(identity))
        elif args.command == "build":
            emit(build(args.profile, args.target, args.verify, args.kind, args.probe,
                       args.device_serial, system_config=args.system,
                       boot_selector=args.boot_selector))
        elif args.command == "ui":
            from tools.content.compiler import compile_system
            emit(compile_system(ROOT,args.output,args.system))
        elif args.command=='music':
            from tools.content.music import compile_music,validate_database
            if args.action=='publish':
                from tools.content.publish import publish_music
                emit(publish_music(args.stage,disk_number=args.disk_number,expected_disk_serial=args.disk_serial,
                                   expected_volume_serial=args.volume_serial,expected_drive=args.drive))
            else:emit(compile_music(args.source,args.output,ffprobe=args.ffprobe,device_root=args.device_root,
                                   verification=args.verification,bypass_cache=args.refresh_metadata,target=args.target,
                                   include_roots=args.include_root,cache_path=args.cache_path) if args.action=='compile' else validate_database(args.database.read_bytes()))
        elif args.command=='video':
            if args.action=='compile':
                from tools.content.ipvf_encode import encode_ipvf
                spec=TARGETS[args.target]
                if not spec['capabilities'].get('video',True):
                    raise ValueError('video is disabled for the selected target')
                if spec['media_video_backend'] == 'bcm-mp4':
                    from tools.content.native_video import prepare
                    from tools.studio.targets import media_profile
                    profile = media_profile(args.target)
                    if args.output.suffix.lower() not in spec['media_video_extensions']:
                        raise ValueError('native video output must use .mp4 or .m4v')
                    if args.fps:
                        if args.fps > profile['native_video']['max_fps']:
                            raise ValueError('frame rate exceeds the target limit')
                        profile['video_fps'] = args.fps
                    emit(prepare(args.source, args.output, profile=profile,
                                 ffmpeg=args.ffmpeg, ffprobe=args.ffprobe))
                else:
                    if args.output.suffix.lower() not in ('.ipvf','.ipv'):
                        raise ValueError('video output must use .ipvf or .ipv')
                    emit(encode_ipvf(args.source,args.output,fps=args.fps or spec['media_video_fps'],
                        width=spec['media_video_width'],height=spec['media_video_height'],
                        color_depth=spec['media_video_color'],
                        max_record_sectors=spec['storage_max_read_sectors'],
                        ffmpeg=args.ffmpeg,ffprobe=args.ffprobe))
            elif args.action=='inspect':
                if args.package.suffix.lower() in ('.mp4', '.m4v'):
                    from tools.content.native_video import inspect_file
                    from tools.studio.targets import media_profile
                    if not args.target:
                        raise ValueError('Specify --target for native MP4 validation')
                    emit(inspect_file(args.package, profile=media_profile(args.target)))
                else:
                    from tools.content.ipvf_validate import inspect_file
                    emit(inspect_file(args.package))
            else:
                from tools.content.publish_video import publish_video
                emit(publish_video(args.package,disk_number=args.disk_number,expected_disk_serial=args.disk_serial,
                     expected_volume_serial=args.volume_serial,expected_drive=args.drive,
                     library_key=args.library_key,title=args.title))
        elif args.command=='photos':
            from tools.content.photos import compile_photos,inspect as inspect_photos
            if args.action=='publish':
                from tools.content.publish_photos import publish_photos
                emit(publish_photos(args.package,disk_number=args.disk_number,expected_disk_serial=args.disk_serial,
                                    expected_volume_serial=args.volume_serial,expected_drive=args.drive))
            else:
                if args.action=='compile':
                    spec=TARGETS[args.target]
                    emit(compile_photos(args.source,args.output,max_dimension=args.max_dimension,
                        viewport_width=spec['media_photo_width'],viewport_height=spec['media_photo_height']))
                else:emit(inspect_photos(args.package))
        elif args.command == "simulator":
            if args.boot_menu:
                if args.tape or args.system or args.all_scenes:
                    raise ValueError("Boot chooser simulation does not accept UI scene options")
                from tools.simulator.boot import simulate_boot
                emit(simulate_boot(args.output,args.target or "classic6g-n25"))
            else:
                from tools.simulator.runner import simulate
                emit(simulate(ROOT,args.output,args.tape,args.system,args.target,args.all_scenes))
        elif args.command == "inspect":
            emit(inspect(args.image.read_bytes()))
        elif args.command == "release":
            emit(verify_release(args.image.read_bytes(), args.symbols.read_text()))
        elif args.command == "storage" and args.action in ("package", "provision"):
            from tools.studio.storage import prepare,provision
            emit(prepare(args.image,args.output) if args.action=="package" else provision(args.package,args.mount,args.serial))
        elif args.command == "report":
            if not args.run_id or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-TZ" for c in args.run_id):
                raise ValueError("invalid run ID")
            emit(json.loads((ROOT / "out/runs" / args.run_id / "receipt.json").read_text()))
        elif args.command == "device" and args.action == "detect-retail":
            from tools.inspect.retail_device import detect
            result = detect(args.mount)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                result["configuration"] = str(args.output.resolve())
            emit(result)
        elif args.command == "device" and args.action == "refresh-session":
            from tools.link import refresh_session
            if args.session_action == "prepare":
                emit(refresh_session.prepare(args.plan, args.plan_sha256, hours=args.hours,install_reviewed_boot=args.install_reviewed_boot, usb_serial=args.usb_serial))
            elif args.session_action == "start":
                emit(refresh_session.start(json.loads(args.prepared.read_text()), allow_prompt=args.allow_uac))
            elif args.session_action in ("install", "verify"):
                state=json.loads(refresh_session.STATE.read_text())
                result=refresh_session.request(state,args.session_action,disk_number=args.disk_number)
                emit(result)
                if not result.get('passed'):return 1
            else:
                if not refresh_session.STATE.is_file():
                    emit(dict(running=False, reason="No refresh session has been started"))
                else:
                    state = json.loads(refresh_session.STATE.read_text())
                    try:
                        emit(dict(refresh_session.request(state, args.session_action), running=args.session_action != "stop"))
                    except (OSError, TimeoutError) as exc:
                        emit(dict(running=False, reason=str(exc)))
        elif args.command == "device" and args.action == "eject":
            from tools.link.eject import eject, eject_reboot
            if args.reboot:
                if bool(args.plan) != bool(args.plan_sha256):
                    raise ValueError("explicit reboot plan requires both --plan and --plan-sha256")
                plan, plan_sha = args.plan, args.plan_sha256
                if not plan:
                    from tools.studio.installer import reboot_plan
                    plan, plan_sha = reboot_plan(args.disk_number, args.expected_serial)
                emit(eject_reboot(args.disk_number, plan, plan_sha, allow_prompt=args.allow_uac))
            else:
                if args.plan or args.plan_sha256 or args.allow_uac:
                    raise ValueError("--plan, --plan-sha256 and --allow-uac require --reboot")
                emit(eject(args.disk_number, args.expected_serial, args.wait_link, args.link_serial))
        elif args.command == "device" and args.action == "prepare-update-history":
            from tools.studio.update_history import provision
            emit(provision(args.mount,args.disk_serial,args.disk_bytes,args.confirmed_build))
        elif args.command == "storage" and args.action == "theme-provision":
            from tools.studio.theme_settings import provision
            emit(provision(args.mount,args.disk_serial,args.disk_bytes,args.confirmed_build))
        elif args.command == "device" and args.action == "native-install":
            from tools.link.native_install import install
            result=install(ROOT/'out/runs',args.package,args.package_sha256,args.port,
                           lambda item:print(json.dumps(item),file=sys.stderr))
            emit(result)
            return 0 if result['passed'] else 2
        elif args.command == "device" and args.action == "update-cycle":
            from tools.link.storage_campaign import update_cycle
            result=update_cycle(ROOT/'out/runs',args.image,args.crash_image,args.port,
                                lambda item:print(json.dumps(item),file=sys.stderr))
            emit(result)
            return 0 if result['automated_passed'] else 2
        elif args.command == "device" and args.action == "storage-sync-cycle":
            from tools.link.sync_campaign import cycle
            result=cycle(ROOT/'out/runs',args.image,args.port,args.disk_number,args.plan,args.plan_sha256,
                         lambda item:print(json.dumps(item),file=sys.stderr))
            emit(result)
            return 0 if result['passed'] else 2
        elif args.command == "device" and args.action == "storage-cycle":
            from tools.link.storage_campaign import cycle
            result=cycle(ROOT/'out/runs',args.image,args.scenario,args.port,
                         lambda item:print(json.dumps(item),file=sys.stderr))
            emit(result)
            return 0 if result['automated_passed'] else 2
        elif args.command == "device" and args.action == "platform-cycle":
            from tools.link.platform_campaign import cycle
            result = cycle(ROOT / 'out/runs', args.image, args.scenario, args.port,
                           lambda item: print(json.dumps(item), file=sys.stderr))
            emit(result)
            return 0 if result['automated_passed'] else 2
        elif args.command == "device" and args.action == "cycle":
            from tools.link.campaign import cycle
            result = cycle(ROOT / "out/runs", args.image, args.scenario, args.port, args.crash_image,
                           lambda item: print(json.dumps(item), file=sys.stderr),
                           args.release_image, args.release_symbols, hang_image=args.hang_image,
                           resume_run=args.resume_run)
            emit(result)
            return 0 if result["passed"] else 2
        elif args.command == "device" and args.action == "sram-bootstrap":
            if args.sram_action == "build":
                from tools.studio.s5l_bootstrap import build as build_monitor
                emit(build_monitor(args.device_serial))
            elif args.sram_action == "prepare":
                from tools.link.s5l_bootstrap import prepare
                emit(prepare(args.mount))
            elif args.sram_action == "update":
                from tools.link.s5l_bootstrap import update
                emit(update(args.prepared))
            elif args.sram_action == "backup-nor":
                from tools.link.s5l_bootstrap import backup_nor
                emit(backup_nor(args.prepared, args.output))
            elif args.sram_action == "prepare-nor":
                from tools.link.classic_nor import prepare
                emit(prepare(args.prepared, args.backup, args.output, args.boot_image))
            elif args.sram_action == "preserve-apple":
                from tools.link.classic_nor import preserve_apple
                emit(preserve_apple(args.prepared, args.backup, args.mount))
            elif args.sram_action == "install-nor":
                from tools.link.classic_nor import install
                emit(install(args.prepared, args.plan_sha256, progress=lambda message: print(message, file=sys.stderr)))
            elif args.sram_action == "diagnose":
                from tools.link.s5l_bootstrap import diagnose
                emit(diagnose(args.prepared, display=args.display))
            else:
                from tools.link.s5l_bootstrap import load
                emit(load(args.prepared, wait_seconds=args.wait_seconds, inspect_only=args.inspect_only, after_reset=args.after_reset,
                          probe_operation={None:None,"identity":0,"memory":1,"storage":2}[args.probe],
                          progress=lambda message: print(message, file=sys.stderr)))
        elif args.command == "device" and args.action in ("bootstrap", "restore", "bootstrap-status"):
            from tools.studio.bootstrap import install, restore, status
            if args.action == "bootstrap":
                emit(install(args.mount, args.image, args.envelope, args.expected_original_sha))
            elif args.action == "restore":
                emit(restore(args.mount))
            else:
                emit(status(args.mount))
        elif args.command == "device":
            from tools.link.transport import SerialTransport
            if args.port:
                from tools.link.campaign import connect
                if args.action == 'boot':
                    print('Waiting for the device startup endpoint before upload.', file=sys.stderr)
                session, connected_device, identity = connect(port=args.port,
                    deadline_seconds=180 if args.action == 'boot' else 15)
                try:
                    if args.action == 'boot' and not identity.get('healthy'):
                        from tools.link.campaign import wait_upload_ready
                        print('Waiting for persistent startup to settle before upload.', file=sys.stderr)
                        session, connected_device, identity = wait_upload_ready(session, connected_device, identity)
                    from tools.link.identity import decode
                    if args.action in ("boot", "reboot", "install", "storage-fault", "storage-recover"):
                        confirmed = decode(session.status())
                        if any(confirmed[key] != identity[key] for key in ("target_id", "build_id", "generation")):
                            raise RuntimeError("device identity changed during mutation preflight")
                    if args.action == "info":
                        emit(dict(port=args.port, identity=identity, status=decode(session.status())))
                    elif args.action == "startup-timing":
                        emit(dict(identity=identity,timing=session.startup_timing(identity['generation'])))
                    elif args.action == "video-startup-timing":
                        emit(dict(identity=identity,timing=session.video_startup_timing()))
                    elif args.action == "boot-timeline":
                        emit(dict(identity=identity,timing=session.boot_timeline(identity['generation'])))
                    elif args.action in MUSIC_ACTIONS:
                        from tools.link.music import command
                        emit(command(session,identity,args.action,path=getattr(args,'path',None),sample=getattr(args,'sample',None)))
                    elif args.action=="media-info":
                        emit(dict(identity=identity,media=session.media_info()))
                    elif args.action=="ui-state":
                        import struct
                        from tools.link.protocol import Command
                        raw=session.request(Command.UI_STATE)
                        if len(raw)!=64 or raw[:8]!=b'UIST\0\0\0\0':raise RuntimeError('Invalid native UI report')
                        names=('magic','reserved','scene','selected','scene_epoch','transitions','paints','painted_pixels','visible_items','dirty','action','arena_used','arena_high','arena_generation','generation','scenes')
                        emit(dict(identity=identity,ui=dict(zip(names,struct.unpack('<16I',raw)))))
                    elif args.action=="native-status":
                        emit(dict(identity=identity,native=session.native_status()))
                    elif args.action=="storage-info":
                        from tools.link.storage_campaign import FIELDS
                        emit(dict(identity=identity,storage=dict(zip(FIELDS,session.storage_state())),update=list(session.update_status())))
                    elif args.action=="storage-fault":
                        session.storage_fault(identity['generation'],args.mode)
                        emit(dict(accepted=True,mode=args.mode,synthetic=True))
                    elif args.action=="storage-recover":
                        session.storage_recover(identity['generation'])
                        emit(dict(accepted=True,note='Storage remount proceeds asynchronously; inspect storage-info.'))
                    elif args.action=="install":
                        emit(session.persistent_install(identity['generation'],args.image.read_bytes()))
                    elif args.action == "reboot":
                        if args.mode=="persistent":session.reboot_persistent(identity['generation'])
                        else:session.reboot({"os":"normal", "boot":"recovery", "disk":"disk"}[args.mode])
                        emit(dict(accepted=True, mode=args.mode, previous_identity=identity))
                    elif args.action == "boot":
                        import hashlib
                        payload = args.image.read_bytes()
                        requested = inspect(payload)
                        session.upload(payload)
                        if session.verify() != hashlib.sha256(payload).digest():
                            raise RuntimeError("staged image hash mismatch")
                        session.boot_ram()
                        emit(dict(accepted=True, image=requested, previous_identity=identity))
                finally:
                    session.close()
            else:
                emit(dict(ports=SerialTransport.discover(), note="Select the known Linnet Link port with --port to handshake."))
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"linnet: {exc}", file=sys.stderr)
        return 1
