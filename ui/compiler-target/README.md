# P98 static component target

`photo4g-p98.json` records the 220x176 RGB565 pixel target, also known by its
`ipod-photo` alias. The compiler emits the ABI in `ui/runtime/ui.h`.

Generated node kinds are1..17 in declaration order. Geometry is absolute and
within the parent. Literal colors are numeric RGB565; standard semantic color references are
0x10000 through 0x1000c in the role order declared in `ui/runtime/ui.h`. An absent resource is UINT32_MAX;
targets are scene indices or0xfffffffe for Sync. Text and static label pointers
refer to immutable generated storage. Each scene includes the single initial
focus node index, or UINT32_MAX.

`LNU1` JSON contains target/ABI, dimensions, selected theme, runtime `themes` layout registry and
`default_theme` index, per-theme scenes/fonts/metrics, ordered base scenes,
RGB565 asset arrays, baked alpha font, and declared native source paths. `LNA1`
is one lowered scene. `LNT1` contains the selected theme, packed assets, font and
license. These formats are canonical ASCII JSON (sorted keys, compact separators,
one trailing newline); they are host artifacts, not device-parsed input.

`LNC1` lists SHA256 and byte length for every generated artifact plus selected
source hashes. Its content ID hashes source provenance and the scene-document
hash. Paths in manifests are repository-relative; generated host paths returned
by the Python API are informational and excluded from identity. No timestamps or
host font discovery enter a normal build. Rebuilding the same input on Windows
and Linux produces identical bytes.

`LNF1` font JSON has bounded cell dimensions (at most 24 x 24), first32,
count95, a glyph-major alpha array and the original font SHA256. Optional
95-entry `advances` provides proportional spacing. Host inputs retain full
alpha cells. Native generation crops each glyph to its nonzero bounding box,
concatenates coverage bytes and emits offset/x/y/w/h descriptors. This is
lossless; cell dimensions and advances do not change. Empty glyphs have zero
width/height. The painter reads the packed immutable data directly.

`ln_ui_scenes` selects one immutable compiled scene table; `ln_ui_font` copies
its immutable font descriptor. The renderer resolves theme colors and metrics
without runtime parsing or allocation. `tools/content/layouts.py` preserves
semantic service bindings while emitting each theme's geometry. List/grid
capacity uses that geometry and the active font/row metrics. Native list/grid
flags store host-computed row height (bits 6–12), columns (13–15), visible rows
(16–19), and cell width (20–27), with bit 31 marking the encoding. Bits 0–5
retain their meanings and 28–30 are reserved. This adds no node fields. The
compiler leaves unknown source flags and values outside these bounds unchanged;
the runtime falls back for unmarked, incomplete or reserved-bit encodings.
Selection, dynamic item counts and clipping remain runtime responsibilities.
Source JSON retains original flags; packing applies only to generated C.
Identical immutable node, item and target arrays share deterministic storage.


The `enabled_scenes` bitmask preserves scene indices while honoring explicit
`[features] photos`, `video`, `files` and `demo` booleans. Disabled services lose menu
links in every theme, and native direct/next/previous navigation skips or rejects
their scene slots. Disabled native descriptors retain their IDs, titles and
positions, with no node array, zero count and no focus. Their full host scene
documents remain available; enabling a feature emits its native nodes again.
Omitted service flags retain the previous enabled behavior; `demo` defaults to
false and enables only the SDK UI Demo when explicitly true. The first
configured scene must remain enabled because it owns startup and Home navigation.
