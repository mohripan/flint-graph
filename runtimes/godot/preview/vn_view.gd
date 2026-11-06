# SPDX-License-Identifier: MIT
# The real exported stage view, with private playtest persistence disabled.
extends "res://runtime/vn_view.gd"

const NEEDS_STORAGE := ["Save", "Load", "Quick save", "Quick load"]

func _small_button(label: String) -> Button:
	var button := super._small_button(label)
	if label in NEEDS_STORAGE:
		button.disabled = true
		button.tooltip_text = "Playtest progress stays in memory. Save a studio revision to keep your writing."
	return button

func _toolbar(action: String) -> void:
	if action in NEEDS_STORAGE:
		return
	super._toolbar(action)
	if action == "Restart":
		_notice.text = "Playtest restarted. Progress stays in memory."

func _read_gallery() -> Array:
	return []

func _read_settings() -> Dictionary:
	return SaveStore.default_settings()

func _settings_saved() -> bool:
	return false  # Each playtest starts from the player's defaults and browser preference.

func _persist_settings() -> void:
	pass  # Settings and read marks last only as long as this playtest.

func _read_marks() -> Dictionary:
	return {}

func _persist_marks() -> void:
	pass

func _read_terms() -> String:
	return ""  # Every playtest shows the license screen players will see.

func _persist_terms() -> void:
	pass  # Accepting in a playtest lasts only as long as the playtest.

func _persist_gallery() -> void:
	pass  # Includes gallery unlocks: never touch user:// during a Studio playtest.

func _overlay_bridge(open: bool) -> void:
	if OS.has_feature("web"):
		var bridge: Variant = JavaScriptBridge.get_interface("FlintPreview")
		if bridge != null:
			bridge.gallery(open)

func _overlay_changed() -> void:
	_overlay_bridge(_gallery_panel.visible or _log_panel.visible or _menu_panel.visible)
