"""Device command registration and execution for the public linnet CLI."""
import json
from pathlib import Path
import sys

from tools.inspect.image import inspect, verify_device_report
from tools.cli.arguments import _record_arguments
from tools.link.music import ACTIONS as MUSIC_ACTIONS
from tools.studio.build import ROOT


def register_device(commands):
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


def run_device(args, emit):
    if args.action == "detect-retail":
        from tools.inspect.retail_device import detect
        result = detect(args.mount)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            result["configuration"] = str(args.output.resolve())
        emit(result)
    elif args.action == "refresh-session":
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
    elif args.action == "eject":
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
    elif args.action == "prepare-update-history":
        from tools.studio.update_history import provision
        emit(provision(args.mount,args.disk_serial,args.disk_bytes,args.confirmed_build))
    elif args.action == "native-install":
        from tools.link.native_install import install
        result=install(ROOT/'out/runs',args.package,args.package_sha256,args.port,
                       lambda item:print(json.dumps(item),file=sys.stderr))
        emit(result)
        return 0 if result['passed'] else 2
    elif args.action == "update-cycle":
        from tools.link.storage_campaign import update_cycle
        result=update_cycle(ROOT/'out/runs',args.image,args.crash_image,args.port,
                            lambda item:print(json.dumps(item),file=sys.stderr))
        emit(result)
        return 0 if result['automated_passed'] else 2
    elif args.action == "storage-sync-cycle":
        from tools.link.sync_campaign import cycle
        result=cycle(ROOT/'out/runs',args.image,args.port,args.disk_number,args.plan,args.plan_sha256,
                     lambda item:print(json.dumps(item),file=sys.stderr))
        emit(result)
        return 0 if result['passed'] else 2
    elif args.action == "storage-cycle":
        from tools.link.storage_campaign import cycle
        result=cycle(ROOT/'out/runs',args.image,args.scenario,args.port,
                     lambda item:print(json.dumps(item),file=sys.stderr))
        emit(result)
        return 0 if result['automated_passed'] else 2
    elif args.action == "platform-cycle":
        from tools.link.platform_campaign import cycle
        result = cycle(ROOT / 'out/runs', args.image, args.scenario, args.port,
                       lambda item: print(json.dumps(item), file=sys.stderr))
        emit(result)
        return 0 if result['automated_passed'] else 2
    elif args.action == "cycle":
        from tools.link.campaign import cycle
        result = cycle(ROOT / "out/runs", args.image, args.scenario, args.port, args.crash_image,
                       lambda item: print(json.dumps(item), file=sys.stderr),
                       args.release_image, args.release_symbols, hang_image=args.hang_image,
                       resume_run=args.resume_run)
        emit(result)
        return 0 if result["passed"] else 2
    elif args.action == "sram-bootstrap":
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
    else:
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
                    payload=args.image.read_bytes()
                    verify_device_report(args.image,inspect(payload),connected_device['serial_number'],identity['target_id'])
                    emit(session.persistent_install(identity['generation'],payload,image_path=args.image))
                elif args.action == "reboot":
                    if args.mode=="persistent":session.reboot_persistent(identity['generation'])
                    else:session.reboot({"os":"normal", "boot":"recovery", "disk":"disk"}[args.mode])
                    emit(dict(accepted=True, mode=args.mode, previous_identity=identity))
                elif args.action == "boot":
                    import hashlib
                    payload = args.image.read_bytes()
                    requested = inspect(payload)
                    verify_device_report(args.image,requested,connected_device['serial_number'],identity['target_id'])
                    session.upload(payload,image_path=args.image)
                    if session.verify() != hashlib.sha256(payload).digest():
                        raise RuntimeError("staged image hash mismatch")
                    session.boot_ram()
                    emit(dict(accepted=True, image=requested, previous_identity=identity))
            finally:
                session.close()
        else:
            emit(dict(ports=SerialTransport.discover(), note="Select the known Linnet Link port with --port to handshake."))
    return 0
