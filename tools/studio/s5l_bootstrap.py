"""Build the Classic SRAM monitor and its temporary BootROM transfer stub."""
import hashlib
import json
from pathlib import Path
import re
from tools.studio.build import ROOT, run, toolchain
from tools.inspect.image import pack


def build(serial):
    if not re.fullmatch(r'[0-9A-F]{16}',serial):
        raise ValueError('Bootstrap requires the observed Classic USB serial')
    chain=toolchain(); out=ROOT/'out/dev/classic6g-n25/bootstrap';out.mkdir(parents=True,exist_ok=True)
    board=ROOT/'targets/classic6g-n25/bootstrap'
    sources=[board.parent/'power.c',ROOT/'hal/s5l8702/core.c',ROOT/'hal/s5l8702/watchdog.c',ROOT/'hal/s5l8702/aes.c',ROOT/'hal/s5l8702/audio.c',ROOT/'hal/arm926/mmu.c',ROOT/'hal/s5l8702/timer.c',ROOT/'hal/s5l8702/irq.c',ROOT/'hal/s5l8702/irq.S',board/'start.S',board/'monitor.c',board/'persistent.c',board/'enter.S',board/'control.c',ROOT/'hal/codecs/cs42l55.c',ROOT/'hal/pmu/pcf50635.c',ROOT/'hal/arm926/cache.c',ROOT/'hal/s5l8702/pcm_dma.c',ROOT/'hal/s5l8702/ata.c',ROOT/'hal/s5l8702/input.c',board.parent/'panel.c',board.parent/'flash.c',ROOT/'hal/s5l8702/spi.c',board.parent/'display.c',ROOT/'hal/s5l8702/lcd_bus.c',board/'storage.c',ROOT/'hal/s5l8702/ata_pio.c',board.parent/'board.c',ROOT/'hal/s5l8702/i2c.c',ROOT/'hal/s5l8702/usb.c',ROOT/'hal/link/link.c',ROOT/'hal/link/dispatch.c',ROOT/'boot/src/linnet_boot.c',ROOT/'boot/src/loader.c',ROOT/'boot/src/sha256.c',ROOT/'kernel/memory.S']
    sources.append(board.parent/'lcd.c')
    probe_sources=[board/'probe.S',board/'probe.c',board/'storage.c',board/'filesystem.c',board.parent/'board.c',ROOT/'hal/s5l8702/i2c.c',ROOT/'hal/s5l8702/ata_pio.c',ROOT/'services/storage/fat32.c',ROOT/'kernel/memory.S']
    inputs=[*sources,*probe_sources,ROOT/'hal/api/power.h',ROOT/'hal/s5l8702/watchdog.h',ROOT/'hal/s5l8702/aes.h',ROOT/'hal/api/audio.h',ROOT/'hal/arm926/mmu.h',ROOT/'hal/s5l8702/usb.h',ROOT/'hal/s5l8702/boot_state.h',ROOT/'hal/s5l8702/timer.h',ROOT/'hal/s5l8702/irq.h',board.parent/'flash.h',ROOT/'hal/s5l8702/spi.h',ROOT/'hal/arm926/cache.h',ROOT/'hal/pmu/pcf50635.h',ROOT/'hal/s5l8702/pcm_dma.h',board.parent/'board.h',ROOT/'hal/api/input.h',ROOT/'hal/api/display.h',ROOT/'hal/api/ata.h',ROOT/'hal/api/core.h',ROOT/'hal/codecs/codec.h',ROOT/'hal/s5l8702/board.h',board.parent/'panel.h',ROOT/'hal/s5l8702/lcd_bus.h',ROOT/'hal/s5l8702/i2c.h',ROOT/'hal/s5l8702/ata_pio.h',ROOT/'services/storage/fat32.h',board/'memory.ld',board/'rom_transfer.S',board/'sram_bridge.S',ROOT/'hal/s5l8702/registers.h',
            ROOT/'hal/api/usb.h',ROOT/'hal/link/link.h',ROOT/'boot/include/linnet_bytes.h',
            ROOT/'boot/include/linnet_boot.h',ROOT/'boot/include/loader.h',ROOT/'boot/include/sha256.h',ROOT/'hal/link/dispatch.h',ROOT/'boot/src/crc32.inc',Path(__file__)]
    inputs.extend([ROOT/'hal/api/platform.h',ROOT/'ui/profiles/color320/boot_font.h'])
    digest=hashlib.sha256(serial.encode())
    for path in inputs:digest.update(path.read_bytes())
    digest.update(json.dumps({k:v['sha256'] for k,v in chain.items()},sort_keys=True).encode())
    build_id=digest.hexdigest()
    (out/'bootstrap_build.h').write_text('#define LINNET_BOOTSTRAP_SERIAL "'+serial+'"\n#define LINNET_BOOTSTRAP_BUILD_BYTES {'+','.join('0x'+build_id[n:n+2] for n in range(0,64,2))+'}\n')
    (out/'linnet_target.h').write_text('#define LINNET_UI_WIDTH 320u\n#define LINNET_UI_HEIGHT 240u\n#define LINNET_DISPLAY_PIPELINE 0\n#define LINNET_STORAGE_MAX_READ_SECTORS 384u\n')
    flags=['-DLINNET_SRAM_MONITOR=1','--target=arm-none-eabi','-mcpu=arm926ej-s','-marm','-Oz','-ffreestanding','-fno-builtin',
           '-fdata-sections','-ffunction-sections','-fno-unwind-tables','-fno-asynchronous-unwind-tables',
           '-Wall','-Wextra','-Werror','-I'+str(ROOT),'-I'+str(ROOT/'boot/include'),'-I'+str(out)]
    objects=[]
    for index,source in enumerate(sources):
        obj=out/f'{index}.o';run([chain['compiler']['path'],*flags,'-c',source,'-o',obj]);objects.append(obj)
    run([chain['linker']['path'], '-m', 'armelf','-T',board/'memory.ld','--gc-sections','-o',out/'monitor.elf',*objects])
    symbols=run([chain['nm']['path'],'-n',out/'monitor.elf'])
    bss_end=re.search(r'^([0-9a-fA-F]+) B __bss_end$',symbols,re.M)
    if not bss_end or int(bss_end[1],16)>0x22016000:
        raise ValueError('Monitor leaves insufficient bounded SRAM upload staging')
    run([chain['objcopy']['path'],'-O','binary',out/'monitor.elf',out/'monitor.bin'])
    run([chain['compiler']['path'],*flags,'-c',board/'sram_bridge.S','-o',out/'sram_bridge.o'])
    run([chain['linker']['path'], '-m', 'armelf','-Ttext=0x08000000','-e','ln_sram_bridge','-o',out/'sram_bridge.elf',out/'sram_bridge.o'])
    run([chain['objcopy']['path'],'-O','binary',out/'sram_bridge.elf',out/'sram_bridge.bin'])
    run([chain['compiler']['path'],*flags,'-c',board/'rom_transfer.S','-o',out/'rom_transfer.o'])
    run([chain['linker']['path'], '-m', 'armelf','-Ttext=0x220284a8','-e','ln_rom_transfer','-o',out/'rom_transfer.elf',out/'rom_transfer.o'])
    run([chain['objcopy']['path'],'-O','binary',out/'rom_transfer.elf',out/'rom_transfer.bin'])
    probe_objects=[]
    for index,source in enumerate(probe_sources):
        obj=out/f'probe-{index}.o';run([chain['compiler']['path'],*flags,'-c',source,'-o',obj]);probe_objects.append(obj)
    run([chain['linker']['path'], '-m', 'armelf','-T',board/'memory.ld','--gc-sections','-o',out/'probe.elf',*probe_objects])
    run([chain['objcopy']['path'],'-O','binary',out/'probe.elf',out/'probe.bin'])
    probe=(out/'probe.bin').read_bytes()
    payload=(out/'monitor.bin').read_bytes();bridge=(out/'sram_bridge.bin').read_bytes();transfer=(out/'rom_transfer.bin').read_bytes()
    if not 32<=len(payload)<=0x10000 or not len(transfer)<=0x178:raise ValueError('Bootstrap payload exceeds SRAM/DFU bounds')
    (out/'monitor.lnos').write_bytes(pack(payload,'dev',build_id,0x22000000,0x22000000,'classic6g-n25'))
    bridge_image=pack(bridge,'dev',build_id,0x08000000,0x08000000,'classic6g-n25')
    (out/'monitor-bridge.lnos').write_bytes(bridge_image)
    report=dict(target_id='classic6g-n25',serial=serial,build_id=build_id,load_address=0x22000000,
                monitor_bytes=len(payload),monitor_sha256=hashlib.sha256(payload).hexdigest(),
                bridge_bytes=len(bridge),bridge_sha256=hashlib.sha256(bridge_image).hexdigest(),
                transfer_sha256=hashlib.sha256(transfer).hexdigest(),probe_sha256=hashlib.sha256(probe).hexdigest(),hardware_verified=False)
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
