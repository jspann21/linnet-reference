# M25 remaining qualification

Development bring-up is complete for the qualified 30 GB / 32 MiB MA146 board.
[QUALIFICATION.md](QUALIFICATION.md) records the exercised behavior. This list
contains remaining acceptance work, not completed implementation history.

- **USB reliability:** isolate intermittent Apple Disk Mode descriptor loss.
  Compare cable/port and cold/manual entry with software handoff. A passing
  roundtrip alone does not close the fault.
- **Power and audio:** measure charging/source transitions, battery operation,
  sleep/wake, shutdown/startup, runtime, and dock line output.
- **Release images:** verify navigation, playback, power, and recovery without
  development services.
- **Sustained workloads:** long audio/video sessions, A/V sync, repeated seeks,
  large catalogs, uncached browsing during playback, JPEG fallback, empty
  folders, and state after restart.
- **Recovery:** initial enumeration recovery, external-bus stalls beyond the
  tested clock-loss case, parser/transaction faults, and memory pressure.
- **Performance:** measure startup, AAC seek, video throughput, wheel response,
  and large-library search before changing budgets.
- **Physical UI:** check readability, clipping, scrolling, brightness, and
  artifacts across currently available themes.

Use the [Link recovery workflow](../../docs/device-link.md#windows-loses-the-ipod-during-disk-mode)
for USB failures. Keep receipts and measurements local. Record a check as complete
only for the hardware and observable actually tested.

Additional Video variants are separate qualification work. Product proposals
belong in the [roadmap](../../docs/roadmap.md), not this hardware checklist.
