# Device menus

Linnet follows the iPod pattern: choose media from Home, use Extras for utilities,
and open Settings for device preferences. Turn the wheel to select a row, press
Select to open it, and press Menu to return to its parent. Selection is retained
when returning. Photos, video, themes, Cover Flow, games, and some audio controls
appear only on supported, enabled targets.

## Default hierarchy

```text
Home
├── Music
│   ├── Playlists → Playlist → Songs
│   ├── Artists → Albums → Songs
│   ├── Albums → Songs
│   ├── Songs
│   ├── Genres
│   ├── Composers
│   ├── Favorites
│   ├── Cover Flow → Album → Songs
│   ├── Search
│   └── More
│       ├── Album Artists
│       ├── Years
│       ├── Folders
│       ├── Bookmarks
│       ├── Recently Added
│       ├── Recently Played
│       └── Most Played
├── Videos → Video → Playback
├── Photos → Album → Grid → Photo
├── Files → Folder → File
│   ├── Audio → Now Playing
│   ├── Video → Playback
│   ├── Image → Preview
│   ├── Text → Reader
│   └── Other files → Byte viewer
├── Extras
│   ├── Games
│   ├── Notes
│   ├── Date & Time
│   └── Sleep Timer
├── Settings
│   ├── Shuffle: Off / Songs
│   ├── Repeat: Off / All / One
│   ├── Edit Menus → Home / Music / Settings / Extras → Item → Show or Hide / Move up / Move down
│   ├── Sound
│   │   ├── EQ: Off / Presets / Custom
│   │   ├── Sound Check or ReplayGain: Off / Track / Album
│   │   ├── Volume limit
│   │   ├── Clicker: Classic / Off / Low / High
│   │   ├── Custom EQ → Bass / Treble, or five bands
│   │   └── Advanced
│   │       ├── Balance
│   │       ├── Channels
│   │       ├── Crossfeed
│   │       ├── Preamp
│   │       └── Dock line out
│   ├── Display
│   │   ├── Brightness
│   │   ├── Backlight timeout
│   │   └── Themes
│   ├── Video Settings → TV Out / TV Signal / Widescreen / TV Connection
│   ├── Date & Time → Set date and time / Time format
│   ├── Power
│   │   ├── Headphones out: Auto-off timeout
│   │   ├── Headphones in: Auto-off timeout
│   │   └── Battery Capacity
│   ├── USB Disk Mode
│   ├── Firmware Info
│   └── About Linnet
├── Shuffle Songs
└── Now Playing → Playback Options
    ├── Shuffle
    ├── Repeat
    ├── Play Queue → Song → Play / Move up / Move down / Remove / Clear queue
    ├── Save queue as playlist
    ├── Sound
    ├── Sleep Timer
    ├── Favorite
    ├── Save / Update bookmark
    ├── Resume bookmark
    ├── Restart track
    ├── Back 10 seconds
    ├── Forward 10 seconds
    └── Stop
```

Shuffle Songs starts the entire library in random order. Shuffle in Settings or
Playback Options changes the current playback queue. Sound and Sleep Timer open
the same controls wherever they are accessed. Menu returns to the menu that
opened them. Custom EQ changes select the Custom preset automatically.

In Sound, Select or Right increases a value and Left decreases it; the wheel
chooses a row. Presets and Custom EQ affect music from both Music and Files.
Changes made during a track transition show **Applying sound...** until playback
can accept them. Saved sound settings restore independently of the saved queue;
starting a song during startup preserves them, and explicit new edits win.

Custom bands range from -6 to +6 dB at 100 Hz, 250 Hz, 1 kHz, 4 kHz and 8 kHz
on Video/Classic; Photo/4G expose the 100 Hz and 8 kHz bands. Bands at or above
half the track's sample rate are bypassed. Positive EQ reserves digital headroom
for overlapping boosts and compensates at the headphone output: raising Bass or
Treble increases that range while keeping other ranges at their previous level.
Spare output gain is reserved before playback, keeping overall gain stable
during band edits at normal listening levels. The reserve shrinks near the
volume limit so flat playback keeps its full output range; boosts near that
ceiling have less available output gain. Changes settle as buffered audio clears.
Preamp provides additional attenuation and is kept independent of compensation.
Off bypasses EQ bands; the other sound controls retain their own settings.
Video's dock line out retains the equalizer's digital headroom.
Classic's dock line out follows the shared output volume.

Pause mutes both the digital signal and the analog output while retaining the
playback position. Resume restores the output after queued audio and gain are ready.

Power's auto-off timers include time spent playing music. Battery Capacity sets
the installed battery's nominal rating in 50 mAh steps; it is not a charge reading.

## Browsing and playback controls

In music lists, Left opens sorting and letter-jump options; Right opens actions
for the selected item. Song actions include Play, Play Next, Add to Queue, Add to
Playlist, and Toggle Favorite. Bookmarks offer resume and removal. Local playlist
rows offer Rename and Delete; tracks inside them also offer reordering and removal.
Playlist creation appears in Playlists and in the Add to Playlist destination menu.
Destructive playlist deletion retains its Cancel-first confirmation.

In Now Playing, the wheel changes volume, Play toggles pause, Left/Right change
tracks, Select opens Playback Options, and Menu returns to music browsing. In a
video, Left/Right seek ten seconds, Select toggles the controls, and Menu exits.
The TV output choice appears when TV Out is Ask.

Files browses the mounted disk, including hidden and system folders. Select opens
a folder or file; Menu returns to its parent and restores the selected row. Left
opens a file's size and text/byte viewing choices; Right reloads the current folder
directly from disk. Large folders have Previous page and Next page rows. In a text
or byte preview, the wheel scrolls and Left/Right change pages. Media opened from
Files returns there with Menu. Its audio Playback Options contain Sound, Sleep
Timer, Restart, Back/Forward 10 seconds, and Stop.

Media Manager prepares sorted folder pages, image pixels, and font-aware text
wrapping on the computer. Files uses those results when available and can browse
the live disk without an index. See [Files behavior and limits](files.md).

For photos, Left/Right change the image, Play toggles a slideshow, and Select
opens zoom, pan, rotation, fit, and slideshow controls. Menu moves back through
the photo hierarchy. Notes and games keep their own reading and game controls.

## Saved customization

Open **Settings → Edit Menus** on the iPod, choose Home, Music, Settings, or
Extras, then select an item to show/hide it or move it up/down. Changes apply
immediately and save automatically. Required items stay included, and each menu
keeps at least one item. Menu returns to the previous editor page.

Supported shortcuts hidden in Media Manager still appear here as `[ ]` so they
can be shown again. The editor changes only shortcut visibility and order, using
compiled screen metadata and cached rows. It does not prepare media, rebuild
libraries, load new screens, or enable features omitted from the firmware.
Games and UI Demo choices stay under Media Manager's control and are excluded
from this editor; their saved selections are preserved.

Under **Settings → Display → Brightness**, turn the wheel to adjust from 5% to
100% in 5% steps. The backlight changes immediately and the value is saved for
restart. Backlight timeout remains a separate control under Display. The footer
shows whether settings are saved, saving, or unavailable for saving.
Saving can wait for playback to pause or stop so settings writes do not compete
with audio; the footer stays at Saving until publication completes.

Media Manager's **Screens** page edits the same saved shortcuts and ordering.
Use matching updated firmware and Media Manager for on-device menu sync. Reconnect
in Disk Mode or choose **Reload from iPod** to see device edits. Saving merges
changes to different menus. If both interfaces changed the same menu differently,
Media Manager stops the save and asks you to reload and review the changes.
Reloading asks before discarding unsaved desktop edits.
Less frequently used music categories appear under More in the saved order.
Optional Home shortcuts such as Notes, Games, and Cover Flow remain available;
the default Home menu groups them by purpose.

Files and Extras are enabled in stock firmware. Defaults adapt to target
capabilities; links to disabled utilities are omitted. Customized menus retain
their saved order and shortcuts.

Settings, USB Disk Mode, and Sound are required menu items. Shuffle, Repeat, and
Edit Menus remain reachable in Settings.

Menu item IDs are stable. The 80-byte version-three menu envelope is shared by
both editors and saved in the version-six `THMS` payload in the existing A/B
theme records, together with brightness, theme selection, and game scores.
`MENUS.BIN` remains the startup fallback for installations without saved shared
menus. See [binary contracts](formats.md) for the format owners.

The structure draws on Apple's [iPod classic User Guide](https://cdsassets.apple.com/live/6GJYWVAV/user/ma1195_ipod_classic_160gb_user_guide.pdf),
especially its Home ordering, Extras grouping, and Menu-to-parent navigation.
