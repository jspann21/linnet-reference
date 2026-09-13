"""Build rigid Linnet native maintenance packages from a hash-pinned Boot plan.

No device access. The exact before-state requires the original directory and an
empty candidate extent. The device rejects any different full firmware SHA
before writing a sector.

Layout: header512, MBR512, old directory512, new directory512, LOS header128
plus zero padding384, then the reviewed64..128KiB candidate extent.
All integer fields are little-endian.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib
from tools.studio.native_bootstrap import load_plan

HEADER_BYTES=512
CANDIDATE_BYTES=65536
PACKAGE_BYTES=68096
MAX_PACKAGE_BYTES=133632


def _digest(data):
    return hashlib.sha256(data).digest()


def _serial(value):
    encoded=value.encode('ascii')
    if not 1<=len(encoded)<=15 or b'\0' in encoded:
        raise ValueError('native package serial must fit15 nonzero ASCII bytes')
    return encoded.ljust(16,b'\0')


def prepare(plan, plan_sha256, outpath):
    plan=Path(plan).resolve()
    manifest,artifacts,original=load_plan(plan,plan_sha256)
    candidate=artifacts['candidate.bin'];image=artifacts['boot.los']
    candidate_bytes=len(candidate)
    package_bytes=2560+candidate_bytes
    if not CANDIDATE_BYTES<=candidate_bytes<=131072 or candidate_bytes%512 or manifest['candidate_write_bytes']!=candidate_bytes:
        raise ValueError('native package requires a reviewed sector-aligned64..128KiB candidate extent')
    payload=image[128:]
    if not 32<=len(payload)<=candidate_bytes or candidate!=payload+bytes(candidate_bytes-len(payload)):
        raise ValueError('candidate must be the exact zero-padded Boot LOS payload')
    start=manifest['candidate_partition_offset'];directory=manifest['directory_partition_offset']
    before=bytearray(original)
    old_directory=artifacts['directory-original.bin']
    if any(before[start:start+candidate_bytes]):
        raise ValueError('new candidate extent is not empty in the expected before-state')
    before[directory:directory+512]=old_directory
    before_hash=_digest(before)
    staged=bytearray(before);staged[start:start+candidate_bytes]=candidate
    staged_hash=_digest(staged)
    staged[directory:directory+512]=artifacts['directory-candidate.bin']
    final_hash=_digest(staged)
    old=manifest['original_osos'];old_start=old['payload_offset'];old_size=old['payload_bytes']
    if _digest(staged[old_start:old_start+old_size]).hex()!=old['payload_sha256']:
        raise ValueError('planned publication changes the original OSOS payload')
    body=(artifacts['mbr.bin']+old_directory+artifacts['directory-candidate.bin']+
          image[:128]+bytes(384)+candidate)
    if len(body)!=package_bytes-HEADER_BYTES:
        raise ValueError('unexpected fixed package component length')
    header=bytearray(HEADER_BYTES)
    struct.pack_into('<4s5I',header,0,b'LNPK',0,package_bytes,98,0,len(original))
    partition_start=manifest['partition_lba']*512
    struct.pack_into('<QQIIQQIIQ',header,24,partition_start,manifest['candidate_disk_offset'],
                     candidate_bytes,len(payload),manifest['directory_disk_offset'],partition_start+old_start,
                     old_size,('release','dev','trace').index(manifest['image']['profile']),manifest['expected_device_bytes'])
    header[80:96]=_serial(manifest['expected_storage_serial'])
    header[96:112]=_serial(manifest['expected_linnet_usb_serial'])
    hashes=(before_hash,staged_hash,final_hash,bytes.fromhex(old['payload_sha256']),
            _digest(artifacts['mbr.bin']),_digest(candidate),_digest(old_directory),
            _digest(artifacts['directory-candidate.bin']),_digest(image),
            bytes.fromhex(manifest['image']['build_id']),_digest(body))
    for index,digest in enumerate(hashes):header[112+index*32:144+index*32]=digest
    struct.pack_into('<I',header,508,zlib.crc32(header[:508]))
    package=bytes(header)+body
    if len(package)!=package_bytes:raise ValueError('invalid encoded package size')
    outpath=Path(outpath).resolve();report_path=outpath.with_suffix(outpath.suffix+'.json')
    if outpath.exists() or report_path.exists():raise ValueError('package output already exists; use a new path')
    outpath.parent.mkdir(parents=True,exist_ok=True)
    report=dict(format='LNPK',package=str(outpath),bytes=len(package),sha256=_digest(package).hex(),
        plan=str(plan),plan_sha256=plan_sha256.lower(),image=manifest['image'],
        expected_storage_serial=manifest['expected_storage_serial'],expected_linnet_usb_serial=manifest['expected_linnet_usb_serial'],
        firmware_before_sha256=before_hash.hex(),firmware_staged_sha256=staged_hash.hex(),
        firmware_final_sha256=final_hash.hex(),candidate_disk_offset=manifest['candidate_disk_offset'],
        directory_disk_offset=manifest['directory_disk_offset'],
        before_state_policy='candidate extent zero and original directory active',
        device_write_attempted=False)
    with outpath.open('xb') as stream:stream.write(package)
    if outpath.read_bytes()!=package:raise OSError('local package readback mismatch')
    with report_path.open('x',encoding='utf-8') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--plan',type=Path,required=True)
    cli.add_argument('--plan-sha256',required=True)
    cli.add_argument('--output',type=Path,required=True)
    args=cli.parse_args()
    print(json.dumps(prepare(args.plan,args.plan_sha256,args.output),indent=2))
