# Linnet agent instructions

Before using Linnet Link or changing anything on a physical iPod, read
`docs/device-link.md` in full and follow its device selection, ownership,
command, evidence, mutation, recovery, and Apple Disk Mode instructions.

Treat `out/`, sibling artifact archives, and prior worktrees as generated data,
not repository context. Do not recursively list, search, summarize, or load them
during normal discovery. Open only an exact artifact required by the current
task, and inspect its size before reading it. Never write documentation, task
notes, transcripts, or research summaries under `out/`; durable documentation
belongs in the tracked source tree.
