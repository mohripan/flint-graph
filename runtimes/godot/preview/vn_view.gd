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
	if action == "Restart":
		super._toolbar(action)
		_notice.text = "Playtest restarted. Progress stays in memory."
