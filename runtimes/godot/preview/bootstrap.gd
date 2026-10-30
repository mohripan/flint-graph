# SPDX-License-Identifier: MIT
extends Control
const Validator = preload("res://preview/validate_story.gd")
const PreviewView = preload("res://preview/game_view.gd")
var _callback: JavaScriptObject
var _bridge: JavaScriptObject
var _used := false

func _ready() -> void:
	if not OS.has_feature("web"): return
	_bridge = JavaScriptBridge.get_interface("FlintPreview")
	_callback = JavaScriptBridge.create_callback(_receive)
	_bridge.install(_callback)

func _receive(arguments: Array) -> void:
	if _used or arguments.size() != 1 or not arguments[0] is String: return
	_used = true
	var envelope: Variant = JSON.parse_string(arguments[0])
	if not envelope is Dictionary: return
	var checked := Validator.validate(envelope["story_json"].to_utf8_buffer(), envelope["notices"].to_utf8_buffer(), envelope["content_hash"])
	if not checked.get("ok", false):
		_bridge.failed(envelope["revision_id"], envelope["content_hash"])
		return
	var game := PreviewView.new()
	game.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(game)
	game.configure(checked["story"], envelope["content_hash"], {})
	_bridge.loaded(envelope["revision_id"], envelope["content_hash"])
