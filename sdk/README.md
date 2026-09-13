# Linnet static UI SDK

Applications are authored in a deliberately constrained TSX language and compiled
to native C. `ui/system/` contains the shell and media scenes. `apps/notes/` is a
UI Demo application with a native waveform canvas. It demonstrates components;
it does not provide note editing or note storage. Its stable ID remains
`local.example.notes`. Set `[features] demo = true` in an explicit system
configuration to expose UI Demo in Home and Extras. Demo is hidden by default. Batch 7 integrates native
audio, photo, video, settings, and recovery services; static TSX describes their
presentation, while the linked native runtime owns service behavior.

Edit `config/system.toml` to select ordered application IDs and a theme. The first
application is the home scene. Every menu destination must be in that selected
set. Build with `python linnet build --profile dev --kind os --batch 7
--device-serial YOUR_SERIAL --verify` (on one line). Compile content alone with:

```console
python linnet ui compile --output out/ui
python linnet ui compile --system config/system.toml --output out/ui
python linnet ui compile --system themes/midnight/system.toml --output out/ui-midnight
```

## Start an app and theme

Run these PowerShell commands from the repository root, choosing unused
destination folders:

```powershell
Copy-Item -Recurse sdk/templates/app apps/starter
Copy-Item -Recurse sdk/templates/theme themes/starter
```

The compiler discovers `apps/*/manifest.toml` and `themes/*/theme.toml`.
Templates under `sdk/templates/` are inactive until copied. The app is a static
screen with a Home menu action; it needs no native callback or private assets.
The theme references the existing shared font, license, music icon, and artwork
at paths valid after copying to `themes/starter/`.

In `config/system.toml`, set `[ui] theme = "local.example.starter-theme"` and
append `"local.example.starter"` to the existing `apps` array. Keep every existing
ID and its order, with `linnet.system.home` first: native services and menu
destinations depend on the selected scenes. Do not replace the array with only
the new app. In `ui/system/home/screen.tsx`, append `'Starter'` to the Home menu's
`items` and `'local.example.starter'` to its matching `targets`. Each target must
have a corresponding label in the same position.

```console
python linnet ui compile --output out/ui-starter
python linnet simulator --output out/simulator-starter
```

The simulator writes `index.html`, rendered frames, and `report.json` for the
native desktop UI. Navigate to Starter with an input tape using `--tape` if
needed; the default preview starts at Home. Use physical-device checks for runtime behavior. Rebuild the OS to include changes; compiling `.lapp` or `.ltheme`
files alone does not install them. Device installation uses the project's
existing verified update/recovery workflow.

Choose unique lowercase dot-separated IDs before distributing another app or
theme. When renaming the app ID, update the manifest, selected app array, and
Home target together. App and theme templates may also be used independently;
retain the current theme when adding only an app. For an alternate system
configuration, first copy the current `config/system.toml`, preserving its full
app list, and pass its path with `--system` to both compile and simulator.

## Static UI language

The compiler accepts one default exported function with no arguments and one
parenthesized JSX return. Import named components from `@linnet/ui`; all imports
must be used as their original names. There are no arbitrary expressions,
functions, loops, spreads, event closures, CSS, implicit imports, or runtime
JavaScript. Unsupported input is rejected, including trailing source.

```tsx
import { Screen, Text, VirtualList } from "@linnet/ui";
export default function Scene() {
  return (
    <Screen>
      <Text x={4} y={4} w={212} h={20} fg="theme.accent">Library</Text>
      <VirtualList x={4} y={28} w={212} h={144}
        count={100000} text="Item " focus={true} />
    </Screen>
  );
}
```

All 17 components share static `x`, `y`, `w`, `h`, `fg`, `bg`, `flags`, `count`,
`index`, `text`, `resource`, `items`, `targets`, `deps`, and `focus` properties.
Coordinates are relative to the parent and lowered to absolute rectangles. The
root covers 220 by 176 pixels. Rectangles must remain inside their parent.
Numbers use `{123}`, booleans `{true}` / `{false}`, and strings use quotes.
Arrays contain quoted strings only. Strings are printable ASCII, maximum 160
characters. JSX text is accepted inside `Text`; entities such as `&amp;` are
decoded during compilation.

Components: `Screen`, `View`, `Text`, `Icon`, `Image`, `VirtualList`, `Menu`,
`Grid`, `Scrollbar`, `ProgressBar`, `StatusBar`, `Dialog`, `Toast`, `AlbumArt`,
`PhotoSurface`, `VideoSurface`, and `CanvasSurface`. Each scene has at most 256
nodes, nesting at most 16, at most 64 static item labels, and at most 1,000,000
virtual items. The native runtime paints visible rows without per-row allocation.

`items={['Music','Settings']}` defines static rows. The matching optional
`targets={['linnet.system.music','linnet.system.settings']}` is resolved to native
scene indices. `@sync` requests the native Sync/Disk Mode action. Without static
items, `count` sets the virtual row count and `text` supplies a numbered prefix.
`index` sets the initial selection or a progress numerator; progress `count` is
its denominator. Scene focus defaults to the first focusable component; set
`focus={true}` for an explicit initial focus. Only one focus node is supported.

Flags are a bit mask: focusable 1, hidden 2, border 4. Lists, menus and grids default
to focusable. Dependency bits are focus 1, selection 2, animation/value 4, content 8,
status 16. Lists, menus, grids and scrollbars default to 3. Set `deps={16}` on a
status bar that should change with hold/headphone state, or `deps={4}` on an
animated canvas. These declarations drive bounded native damage updates.

App `manifest.toml` contains `[app]` with `id`, `title`,
`entry`, and `capabilities=["ui"]`. IDs are dot-separated lowercase identifiers.
An optional `[assets]` table maps names to P3 PPM files relative to the manifest;
use the full identifier `app.id.assetname` in TSX. Paths must remain inside the source
repository. Selected files are hashed in the content manifest.

Themes live in `themes/*/theme.toml`. `linnet.theme.default` and
`local.example.midnight` demonstrate one-command color customization. Color
tokens resolve from `fg="theme.accent"` or `bg="theme.panel"`; literal `#RRGGBB`
colors are also accepted. Required tokens are foreground, background, accent,
muted, and panel. Optional semantic roles are selection_fg, selection_bg,
status_fg, status_bg, border, artwork_fg, artwork_bg, and battery. These thirteen roles
compile to numeric references and resolve against the active runtime palette.
Literal colors and custom color tokens remain fixed RGB565 values, so use the
standard roles for UI that should follow every theme. Theme metrics permit
row_height16..32 and padding0..12. The default layout retains row_height22/padding4;
other layouts lower authored TSX into their own native rectangles. Assets compile
to RGB565, at most 64 resources / 256 KiB combined.
P3 PPM sources use range 255 and at most 220 by 176 pixels.

The bundled `linnet.theme.album-colors` theme uses `[theme] style="album-art"`.
All thirteen semantic colors follow the current music artwork on every screen,
with a 250 ms transition. Rockbox Photo's 4,096-bucket, every-fourth-pixel
histogram and saturation-weighted scoring select the unmodified background.
The foreground uses its contrasting accent calculation, including the
100-point luminance threshold and proportional channel scaling. Selection
inverts those two roles; quiet surfaces blend toward the inverse background.
Extraction is cached by artwork revision. Missing artwork keeps the previous
palette for one second before returning to authored fallback colors. Actual
photos/video retain their original pixels. Backgrounds can be light or dark.

The checked-in FONT pack is DejaVu Sans Mono, baked to 95 printable ASCII glyphs,
8 by 14 alpha cells, advance 8. Its license is included in every compiled content
package. Baking a replacement is an explicit host step requiring Pillow:

```console
python -m tools.content.font --font path/to/licensed-font.ttf --output themes/my-theme/font.json
```

Set `[theme] font="font.json"` and `font_license="FONT-LICENSE.txt"` to select a
baked font and its redistribution license. Normal content compilation uses only
the Python standard library and never loads a host font or image codec.

Theme fonts may use cells up to 24 by 24 pixels and an optional 95-entry
`advances` array for proportional spacing. Native output deduplicates identical
fonts and losslessly crops each glyph to its nonzero alpha rectangle. An
8-byte glyph descriptor stores the packed alpha offset and original cell
`x,y,w,h`; empty glyphs have zero width and height. The renderer restores those
coordinates while preserving the font's cell height and advance. Baked FONT
JSON retains its full alpha cells. No quantization or runtime allocation is used.

Canvas callbacks are trusted native code, statically linked into the generated
translation unit. Add `canvas` to the capability list and declare, for example,
`[canvas] waveform={source="canvas.c",symbol="ln_notes_waveform"}`. Reference it
as `canvas="local.example.notes.waveform"` on `CanvasSurface`. The function takes
`const struct ln_ui_canvas_context *`; it must obey both its rectangle and clip,
perform bounded work, and avoid allocation or hardware access. The example
checks every pixel against that clip. Callback sources are hashed and compiled
with the same ARM compiler as the application; the TSX compiler does not sandbox
native C. Sixteen callbacks maximum are accepted. There is no device-side module
loader or callback registration.

Compiler output includes `linnet_ui.c`, `scenes.json`, `content-manifest.json`,
font license, and compiled `.lapp` / `.ltheme` JSON packages. Those packages are
host artifacts; the device consumes only the linked native definitions. The
desktop oracle uses the same generated definitions and font data.

## Runtime theme selection

The compiler bundles up to 16 themes from `themes/*/theme.toml`. `[theme]`
accepts a printable `name` (maximum 24 characters) and `style`: `standard`,
`monochrome`, or `apple-photo`. Styles select flat UI, two-color text and artwork
with a centered underlined header, or a silver header and blue-style selection
gradient. The `layout` preset is `default`, `ipod-photo`, `graphite`, `aurora`,
`sunset`, or `blueprint`. Each theme compiles its own complete static scene
table, font descriptor, palette and metrics. The five shipped additions are
`linnet.theme.ipod-photo`, `linnet.theme.graphite`, `linnet.theme.aurora`,
`linnet.theme.sunset`, and `linnet.theme.blueprint`.

Append `linnet.system.themes` to selected app arrays when adopting the theme
picker in an older system configuration. Settings links to this scene. Wheel
selects a row, Select applies immediately, and an asterisk marks the active
choice. Menu returns to Settings. The default `[ui] theme` selects the initial
scene table and font and supplies the shared asset pack. Runtime selection
switches the active scene pointer and font descriptor as well as palette and
metrics. Scene IDs and order remain stable across themes so service bindings
and navigation remain valid. Dynamic album art, photos and video keep their
source pixels.

Native canvas callbacks receive resolved `fg` and `bg` in their context. Use
these instead of literal colors. Firmware preferences are memory-only hooks
into the display settings owner; rendering never performs storage I/O.

Optional `THEME0.BIN` and `THEME1.BIN` persist the selected stable theme ID.
See [binary contracts](../docs/formats.md) for their independent transactional record.
