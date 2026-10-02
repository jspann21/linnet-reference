# Binary contracts

Use this page to find the owner of a binary format. Exact field offsets, accepted
identifiers, lengths, and limits belong with the encoder and reader, rather than
a second handwritten specification.

Most records use little-endian integers and CRC32/ISO-HDLC. Each reader enforces
its own reserved fields and bounds. IPVF has different pixel byte order and CRC
rules; see its [format guide](video-format.md). Do not assume all headers have the
same version field or that every reserved field is a version.

## Firmware and state

| Record | Purpose | Definition and reader |
| --- | --- | --- |
| `LNOS` / `.los` | 128-byte image header followed by an ARM payload; target, profile, entry, length, build identity, and CRCs | [Boot API](../boot/include/linnet_boot.h), [host image inspector](../tools/inspect/image.py) |
| `BOOT`, `CRSH`, `LNID` | Boot selection, development crash mailbox, and device identity | [Boot API](../boot/include/linnet_boot.h), [host identity](../tools/link/identity.py) |
| `STAT` | Redundant 512-byte state copies with generation, bounded payload, and CRC | [State store](../services/state/store.c) |
| `UPDT`, `HAND`, `RLBK` | Persistent image slots, retained handoff, and failed-candidate information | [Update owner](../services/update/update.c) |
| `LNPK` | Fixed, reviewed native maintenance package; not arbitrary raw-sector access | [Package builder](../tools/studio/native_package.py), [Photo writer](../targets/photo4g-p98/native_update.c) |
| `SETT`, `THMS` | User settings and stable theme selection | [Display settings](../services/display/settings.c), [storage owner](../services/storage/storage.c) |
| `HIST`, `HPGE` | Redundant paged playback history | [History records](../services/music/history_record.h), [page owner](../services/music/history_pages.c) |
| `MSET`, `QUEU`, `PROF` | Music queue and sound state | [Music settings](../services/music/settings.c), [queue](../services/music/queue.c), [profile](../services/music/profile.c) |

State generations order publications; they are not product versions. A valid
checksum does not make an incompatible layout acceptable. Build identity,
payload checksum, and full-image hash have distinct meanings.

## Content and transport

| Format | Guide or implementation |
| --- | --- |
| `PODB` music index | [Music library](music-format.md) |
| `LPIC` prepared photos | [Prepared photos](photo-format.md) |
| `IPVF` and native MP4 video | [Video formats](video-format.md) |
| `NOTE` notes and `LDSP` DSP profiles | [Notes compiler](../tools/content/notes.py), [DSP compiler](../tools/content/dsp.py) |
| `FONT`, `LNUI`, `APPL`, `THME`, `CNTN` | [UI compiler](ui-compiler.md); these are host artifacts |
| `LINK` USB frames and diagnostic records | [Linnet Link](device-link.md#protocol-reference) |

When changing a format, update its producer, validator, device reader, and
publication path together. Check truncation, overflow, references, and unknown
values. Existing data must either remain supported or be rejected with a clear
rebuild/recovery path. Hashes and CRCs provide integrity, not authentication.
