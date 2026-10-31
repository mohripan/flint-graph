# SPDX-License-Identifier: MIT
# The real exported stage view, with private playtest persistence disabled.
extends "res://runtime/vn_view.gd"

func _small_button(label: String) -> Button:
	var button := super._small_button(label)
	if label in ["Save", "Load"]:
		button.disabled = true
		button.tooltip_text = "Playtest progress stays in memory. Save a studio revision to keep your writing."
	return button

func _toolbar(action: String) -> void:
	if action in ["Restart", "Gallery", "License"]:
		super._toolbar(action)
		if action == "Restart":
			_notice.text = "Playtest restarted. Progress stays in memory."

func _read_gallery() -> Array:
	return []

func _read_volume() -> int:
	return 100

func _persist_volume() -> void:
	pass  # The voice volume lasts only as long as this playtest.

func _read_terms() -> String:
	return ""  # Every playtest shows the license screen players will see.

func _persist_terms() -> void:
	pass  # Accepting in a playtest lasts only as long as the playtest.

func _persist_gallery() -> void:
	pass  # Includes gallery unlocks: never touch user:// during a Studio playtest.

func _gallery_bridge(open: bool) -> void:
	if OS.has_feature("web"):
		var bridge: Variant = JavaScriptBridge.get_interface("FlintPreview")
		if bridge != null:
			bridge.gallery(open)

func _open_gallery() -> void:
	super._open_gallery()
	_gallery_bridge(true)

func _close_gallery() -> void:
	super._close_gallery()
	_gallery_bridge(false)
