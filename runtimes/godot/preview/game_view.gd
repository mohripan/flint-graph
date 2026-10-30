# SPDX-License-Identifier: MIT
# The real exported player/view, with private playtest persistence disabled.
extends "res://runtime/game_view.gd"

func _button(label: String, light: bool = false) -> Button:
	var button := super._button(label, light)
	if label in ["Save", "Load"]:
		button.disabled = true
		button.tooltip_text = "Playtest progress stays in memory. Save a studio revision to keep your writing."
	return button

func _toolbar(action: String) -> void:
	if action == "Restart":
		super._toolbar(action)
		_notice.text = "Playtest restarted. Progress stays in memory."
