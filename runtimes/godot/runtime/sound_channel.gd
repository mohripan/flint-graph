# SPDX-License-Identifier: MIT
# One looping channel of background sound (ADR 0066): a new track crossfades over the old one.
extends RefCounted

const FADE_SECONDS := 1.0
var current: Variant = null
var _players: Array[AudioStreamPlayer] = []
var _front := 0
var _fade := 1.0  # How far the front player has faded in; 1.0 when nothing is changing.
var _volume := 1.0


static func decibels(fraction: float) -> float:
	return linear_to_db(fraction) if fraction > 0.0 else -80.0


func _init(parent: Node) -> void:
	for index in range(2):
		var player := AudioStreamPlayer.new()
		parent.add_child(player)
		_players.append(player)


func change(id: Variant, stream: AudioStream, instantly: bool) -> void:
	if id == current:
		return
	current = id
	_front = 1 - _front
	var incoming := _players[_front]
	incoming.stop()
	incoming.stream = stream
	_fade = 0.0
	_apply()
	if stream != null:
		incoming.play()
	if instantly:
		_finish()


func tick(delta: float) -> void:
	if _fade >= 1.0:
		return
	_fade = minf(1.0, _fade + delta / FADE_SECONDS)
	_apply()
	if _fade >= 1.0:
		_finish()


func set_volume(fraction: float) -> void:
	_volume = fraction
	_apply()


func playing() -> bool:
	return _players[_front].playing


func fading() -> bool:
	return _fade < 1.0


func audible_players() -> int:
	var count := 0
	for player: AudioStreamPlayer in _players:
		if player.playing:
			count += 1
	return count


func front_volume_db() -> float:
	return _players[_front].volume_db


func _finish() -> void:
	_fade = 1.0
	_apply()
	var outgoing := _players[1 - _front]
	outgoing.stop()
	outgoing.stream = null


func _apply() -> void:
	_players[_front].volume_db = decibels(_volume * _fade)
	_players[1 - _front].volume_db = decibels(_volume * (1.0 - _fade))
