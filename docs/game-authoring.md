# Creating Linnet games

**Status:** proposed standard. The external game loader and SDK are not implemented
yet; exact package fields, interface signatures, and budgets need pilot validation.

Performance comes first. Standardize layout, interfaces, and build tools without
adding runtime overhead for author convenience.

## Project layout

```text
games/author.game/
  game.toml             # Identity, compatibility, capabilities, budgets
  README.md             # Gameplay, controls, build/preparation notes
  LICENSE
  src/                  # Native game logic and drawing
  assets/               # Source artwork, fonts, sound definitions
  levels/               # Authored levels and other source data
  tools/                # Optional host preparation scripts
  out/                  # Generated target packages/reports; ignored
```

Use one source project with target-specific artwork or code where beneficial.
Install runtime code, prepared data/assets, and required notices. Keep source
assets, preparation scripts, and debugging symbols on the host.

## Required metadata

- Permanent lowercase ASCII namespaced ID, such as `author.game`; name,
  description, version, author, and license. Versions/device variants share an ID;
  forks receive a new one. Define identity bounds and reject duplicates.
- Supported devices/display sizes, interface/layout versions, and required
  services such as music-library access.
- Code/data, zeroed state, assets, stack, temporary-memory limits, and update/frame
  budgets for each target.
- Score/progress schema version and maximum record size, when used.

New games must add no firmware registry entry or per-game firmware dependency.
The catalogue supports bounded, extensible identities; preserve legacy IDs/scores.

## Native interface

Keep state inside the game. Use bounded initialization, input, update/deadline,
draw, and shutdown callbacks. Firmware owns scheduling and provides a small
versioned service table for drawing, input, time, audio, and saved state.

Use the SDK's target linker layout and public services. Compatible firmware must
preserve both the layout and interface contracts. Avoid private firmware
addresses, shared game globals, and arbitrary background callbacks.

Declare optional services. Release effects/music sessions on exit. Firmware owns
bounded, identity-bound save records and pending save copies, and drains storage
work before unloading game memory.

## Prepare on the host

- Compile target-specific native code; remove unused code and resources.
- Crop, scale, and pack artwork for the actual display. Prepare palettes,
  transparency spans, glyph subsets, and text metrics where useful.
- Validate levels; prepare paths, lookup tables, collision/spatial data, and audio
  cues when measurements justify the storage and memory cost.
- Generate resource offsets, metadata, and the Games catalogue in advance.

Keep input-dependent gameplay on-device. Precomputation must improve the result;
oversized tables can increase loading time and memory use.

## Performance requirements

- Use native code and prepared binary data. Keep source parsing, asset conversion,
  font generation, and level preprocessing off the device.
- Pre-size state/buffers. Avoid per-frame allocation and blocking reads in
  input/update/draw callbacks.
- Prefer integer/fixed-point hot paths. Select compiler settings using measured
  speed and size, rather than minimizing bytes indiscriminately.
- Draw changed regions, use deadlines, and sleep when idle. Use bulk drawing
  operations instead of per-pixel indirect service calls.
- Measure asset encodings and compression, including decode time, scratch RAM,
  and launch latency. Smaller files do not justify slower gameplay. Keep hot code
  and frequently drawn assets ready to use.
- Respect audio deadlines and buffer ownership. Add no interpreter, general engine,
  or dependency layer solely to simplify authoring.
- Enforce target memory/performance limits; author convenience cannot waive them.

## Build and acceptance

1. Author the project, run host preparation, and build the target variants.
2. Inspect compatibility, dependencies, and download/installed/resident/peak-memory
   reports. Do not serialize zero-filled state or unused load-slot padding.
3. Preview gameplay/rendering, then measure worst-case frames, launch, RAM, and
   playback coexistence on hardware. Desktop previews cannot validate ARM loading
   or executable caches.
4. Install prepared files through Media Manager. Players need no compiler. A host
   archive may contain multiple variants; install only the matching one and its
   assets. Installation never runs package-supplied preparation scripts.
5. Verify a new game uses only the public layout/interface, installs and removes
   with unchanged firmware, preserves scores on reinstall, and works across a
   compatible firmware rebuild.
