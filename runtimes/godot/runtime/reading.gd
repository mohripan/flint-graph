# SPDX-License-Identifier: MIT
# How a player reads a story (ADR 0064): text speed, auto-advance timing, the backlog's size
# and read marks. Nothing here touches story state, so no setting can change a route.
extends RefCounted

# Characters per second; zero shows the whole line at once.
const TEXT_SPEEDS := {"instant": 0.0, "fast": 120.0, "normal": 60.0, "slow": 30.0}
# Multiplies how long auto-advance leaves a line on screen.
const AUTO_SPEEDS := {"fast": 0.6, "normal": 1.0, "slow": 1.6}
const DEFAULT_TEXT_SPEED := "normal"
const DEFAULT_AUTO_SPEED := "normal"
const BACKLOG_LIMIT := 300
const SKIP_SECONDS := 0.06
const AFTER_VOICE_SECONDS := 0.6
const FLUSH_SECONDS := 5.0
const MAX_REVEAL_SECONDS := 8.0
const MAX_AUTO_SECONDS := 14.0
const MAX_READ_MARKS := 20000


static func reveal_seconds(text: String, speed: String) -> float:
	var rate: float = TEXT_SPEEDS.get(speed, 0.0)
	if rate <= 0.0:
		return 0.0
	return minf(text.length() / rate, MAX_REVEAL_SECONDS)


static func auto_seconds(text: String, speed: String) -> float:
	var seconds := minf(1.2 + text.length() * 0.045, MAX_AUTO_SECONDS)
	return seconds * float(AUTO_SPEEDS.get(speed, 1.0))


# Includes the text, so a line the creator rewrote counts as unread again.
static func read_mark(node_id: String, text: String) -> String:
	return node_id + ":" + String.num_int64(text.hash(), 16)
