# Performance work

This is the remaining performance and qualification backlog. Completed changes
are recorded in Git. Product work is tracked in the [roadmap](docs/roadmap.md).

| Area | Remaining work | Code |
| --- | --- | --- |
| Whole-operation timing | Compare cold and warm discovery, preparation, conversion, verification, and publication on rotating and flash storage. Isolated improvements do not establish an overall speedup. | [Media status](tools/content/media_status.py), [preparation](tools/content/media_manager.py) |
| Portable storage handoff | The HAL interface change is implemented. Qualify the Classic's Apple handoff and AES path on hardware before closing the work. | [Storage](services/storage/storage.c), [platform API](hal/api/platform.h) |
| Idle power | Measure wake sources and the clock-switch break-even point on the monochrome Q21, which enables idle clock switching. Include battery and external power. | [Runtime](kernel/runtime.c) |
| Playback scheduling | Measure artwork, photo, metadata, and next-track work competing at a track boundary. Keep PCM reserve and gapless behavior intact when tuning budgets. | [Music controller](services/music/controller.c), [player](services/music/player.c) |
| Classic video | Measure decoder startup stages and buffer use before changing frame buffers or priming thresholds. The Video target uses a different BCM backend. | [Native player](services/video/native/player.c), [decoder](services/video/native/decoder.c) |
| Classic display | Measure framebuffer preservation and panel transfer costs for small updates. Validate alternating buffers, theme acknowledgement, and physical tearing before changing transfers. | [Display](targets/classic6g-n25/display.c), [panel](targets/classic6g-n25/panel.c) |

Use existing counters, profiling tools, and device checks. Keep comparable
workloads and distinguish host timing, emulator instructions, device counters,
and physical observations. A proposed optimization should state what improved
and what was checked for regressions.

Keep measurements, media details, build identities, and device receipts in
[local artifacts](docs/local-artifacts.md). Do not add benchmark transcripts to
this list.
