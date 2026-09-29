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
├── Extras
│   ├── Games
│   ├── Notes
│   ├── Date & Time
│   └── Sleep Timer
├── Settings
│   ├── Shuffle: Off / Songs
│   ├── Repeat: Off / All / One
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

For photos, Left/Right change the image, Play toggles a slideshow, and Select
opens zoom, pan, rotation, fit, and slideshow controls. Menu moves back through
the photo hierarchy. Notes and games keep their own reading and game controls.

## Saved customization

Media Manager's **Screens** page can reorder or hide supported shortcuts.
Less frequently used music categories appear under More in the saved order.
Optional Home shortcuts such as Notes, Games, and Cover Flow remain available;
the default Home menu groups them by purpose.

Menu item IDs remain stable. The version-three `MENUS.BIN` writer keeps the
80-byte envelope and checksum. Firmware and Media Manager accept versions one
through three. Recognized older default menus adopt the new hierarchy, including
defaults filtered for target capabilities. Custom orders and selected shortcuts
are retained. Settings and USB Disk Mode remain required navigation anchors;
Sound, Shuffle, and Repeat remain reachable in Settings.

The stock Photo and Video configurations use the previously disabled Files scene
slot for Extras, within the 32-scene limit. Custom firmware can still select Files;
optional links to unselected, disabled utilities are omitted during compilation.

The structure draws on Apple's [iPod classic User Guide](https://cdsassets.apple.com/live/6GJYWVAV/user/ma1195_ipod_classic_160gb_user_guide.pdf),
especially its Home ordering, Extras grouping, and Menu-to-parent navigation.
