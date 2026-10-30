# Classic runtime power

Classic OS uses three CPU rates: 54 MHz for light work, 108 MHz for work that
needs more headroom, and the existing 216 MHz video boost. Boot and the resident
monitor retain their original clock policy. Hardware results belong in local
qualification artifacts; no battery-life percentage is inferred from clocks.

## Clock selection

The 54 MHz state enables only the CPU divide-by-two field in `0x3c500004`.
The normal source remains PLL0 at 108 MHz. AHB stays at 54 MHz and APB at 27 MHz.
The SDRAM timing, audio source, peripheral clocks, external timer and voltage
settings are preserved. Lower CPU frequency reduces its active clock rate;
it does not by itself establish an energy saving for a fixed amount of work.

The foreground policy requests 108 MHz during startup, storage transfers,
display work, user activity, media opening/seeking, and other busy services.
Music may enter 54 MHz with one second of PCM queued and returns to 108 MHz
below half a second. A slow foreground turn delays another low-clock attempt
for two seconds. An underrun disables low-clock playback for that player
generation. Failed clock transitions disable the optimization and restore the
normal clock; failure to restore stops further executive work.

The policy leaves video clock ownership with the video service. Handoffs restore
108 MHz so older Boot and monitor code receive the original clock layout.

## Idle deadlines

The wheel wakes the OS by interrupt. Hold and headphone switches, including
headset remote sampling, have an explicit 20 ms deadline. Release OS may wait
up to that deadline rather than waking every 5 ms. Earlier audio, storage,
display, power and service deadlines still take precedence. Development Link
retains its 1 ms USB poll ceiling.

## Evidence

`python linnet device classic-power-state --serial <Linnet-USB-serial>` reads
live clock registers, clock residency, queue headroom, transition failures,
fallback counters and peripheral clock gates. Residency includes WFI; it is
not active CPU time or a current measurement. Changes should be qualified
against idle/wake, playback formats, pause/resume, seeking, storage recovery,
video boost/restoration and headset controls on each hardware revision.

Register facts are described in the public
[S5L clock register definitions](https://raw.githubusercontent.com/Rockbox/rockbox/master/firmware/export/s5l87xx.h)
and [clock-domain notes](https://raw.githubusercontent.com/Rockbox/rockbox/master/firmware/target/arm/s5l8702/clocking-s5l8702.h).
These references describe hardware; Linnet's policy and implementation are
original and incorporate no Rockbox implementation code.
