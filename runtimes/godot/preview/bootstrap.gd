# SPDX-License-Identifier: MIT
extends Control
const Validator = preload("res://preview/validate_story.gd")
const PreviewView = preload("res://preview/game_view.gd")
const PreviewStage = preload("res://preview/vn_view.gd")
# The bridge copies one asset at a time into the engine's in-memory file system.
const STAGED := "/tmp/flint-preview-asset"
var _callback: JavaScriptObject
var _bridge: JavaScriptObject
var _used := false

func _ready() -> void:
	if not OS.has_feature("web"): return
	_bridge = JavaScriptBridge.get_interface("FlintPreview")
	_callback = JavaScriptBridge.create_callback(_receive)
	_bridge.install(_callback)

func _pull(ids: Array) -> Variant:
	# Story format 2 (ADR 0040): bytes never pass through JSON, base64 or eval.
	var assets := {}
	for index in ids.size():
		if not ids[index] is String or assets.has(ids[index]) or not _bridge.take(index): return null
		var file := FileAccess.open(STAGED, FileAccess.READ)
		if file == null or file.get_length() > 10485760:
			return null
		assets[ids[index]] = file.get_buffer(file.get_length())
		file.close()
		DirAccess.remove_absolute(STAGED)
	return assets

func _receive(arguments: Array) -> void:
	if _used or arguments.size() != 1 or not arguments[0] is String: return
	_used = true
	var envelope: Variant = JSON.parse_string(arguments[0])
	if not envelope is Dictionary: return
	var assets: Variant = _pull(envelope["assets"]) if envelope.get("assets") is Array and envelope["assets"].size() <= 256 else null
	if assets == null:
		_bridge.failed(envelope["revision_id"], envelope["content_hash"])
		return
	var checked := Validator.validate(envelope["story_json"].to_utf8_buffer(), envelope["notices"].to_utf8_buffer(), envelope["content_hash"], assets)
	if not checked.get("ok", false):
		_bridge.failed(envelope["revision_id"], envelope["content_hash"])
		return
	var game: Control = PreviewStage.new() if checked["story"]["schema_version"] == "2" else PreviewView.new()
	game.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(game)
	game.configure(checked["story"], envelope["content_hash"], assets)
	_bridge.loaded(envelope["revision_id"], envelope["content_hash"])
