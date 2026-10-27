# SPDX-License-Identifier: MIT
# Story strings render as plain text. Only current-node images are retained.
extends Control

const PlayerScript = preload("res://runtime/player.gd")
const SaveStore = preload("res://runtime/save_store.gd")
const DisplayFont = preload("res://fonts/Lora.ttf")
const INK := Color("182635")
const FOG := Color("dce5ea")
const SLATE := Color("4e6577")
const LAMP := Color("d5ae68")
const PAPER := Color("f0f4f6")
var _source: Dictionary
var _hash: String
var _assets: Dictionary
var _player: RefCounted
var _margin: MarginContainer
var _title: Label
var _notice: Label
var _scroll: ScrollContainer
var _stage: Control
var _background: TextureRect
var _portrait: TextureRect
var _speaker: Label
var _text: RichTextLabel
var _choices: VBoxContainer
var _buttons: Array[Button] = []
var _last_background: Variant = null
var _last_portrait: Variant = null
var _qa := false


func configure(source: Dictionary, package_hash: String, assets: Dictionary) -> void:
	_source = source
	_hash = package_hash
	_assets = assets.duplicate()
	_player = PlayerScript.new(source, package_hash)
	_build()
	resized.connect(_resize_layout)
	_resize_layout()
	_render()
	# Optional inspection must never be a prerequisite for the actual game UI.
	if OS.has_feature("web"):
		var browser: Variant = JavaScriptBridge.get_interface("window")
		if browser != null:
			var query: Variant = browser.location.search
			if query is String:
				_qa = query.trim_prefix("?").split("&").has("qa=1")
		_publish_qa.call_deferred()


func _box(fill: Color, border: Color, width: int = 1) -> StyleBoxFlat:
	var box := StyleBoxFlat.new()
	box.bg_color = fill
	box.border_color = border
	box.set_border_width_all(width)
	box.set_corner_radius_all(12)
	box.content_margin_left = 20
	box.content_margin_right = 20
	box.content_margin_top = 14
	box.content_margin_bottom = 14
	return box


func _button(label: String, light: bool = false) -> Button:
	var button := Button.new()
	button.text = label
	button.custom_minimum_size.y = 46
	button.focus_mode = Control.FOCUS_ALL
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.add_theme_font_size_override("font_size", 16)
	for role: String in ["font_color", "font_hover_color", "font_focus_color", "font_pressed_color"]:
		button.add_theme_color_override(role, INK if light else FOG)
	button.add_theme_stylebox_override("normal", _box(PAPER if light else INK, SLATE))
	button.add_theme_stylebox_override("hover", _box(Color("e4ecf0") if light else Color("293e51"), LAMP))
	button.add_theme_stylebox_override("pressed", _box(Color("dce5ea") if light else Color("344c60"), LAMP))
	button.add_theme_stylebox_override("focus", _box(Color.TRANSPARENT, LAMP, 3))
	return button


func _build() -> void:
	var ground := ColorRect.new()
	ground.color = INK
	ground.mouse_filter = Control.MOUSE_FILTER_IGNORE
	ground.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(ground)
	_margin = MarginContainer.new()
	_margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_margin)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 14)
	_margin.add_child(column)
	_title = Label.new()
	_title.text = _source["title"]
	_title.clip_text = true
	_title.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	_title.add_theme_font_override("font", DisplayFont)
	_title.add_theme_color_override("font_color", FOG)
	column.add_child(_title)
	var toolbar := HBoxContainer.new()
	toolbar.add_theme_constant_override("separation", 8)
	column.add_child(toolbar)
	for item: String in ["Save", "Load", "Restart"]:
		var button := _button(item)
		button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		button.pressed.connect(_toolbar.bind(item))
		toolbar.add_child(button)
	_notice = Label.new()
	_notice.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_notice.add_theme_color_override("font_color", LAMP)
	_notice.add_theme_font_size_override("font_size", 14)
	column.add_child(_notice)
	_scroll = ScrollContainer.new()
	_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	column.add_child(_scroll)
	var content := VBoxContainer.new()
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.add_theme_constant_override("separation", 16)
	_scroll.add_child(content)
	_stage = Control.new()
	_stage.clip_contents = true
	content.add_child(_stage)
	_background = TextureRect.new()
	_background.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_background.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	_background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_stage.add_child(_background)
	_portrait = TextureRect.new()
	_portrait.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_portrait.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	_portrait.anchor_left = 0.6
	_portrait.anchor_right = 0.95
	_portrait.anchor_bottom = 1.0
	_portrait.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_stage.add_child(_portrait)
	var panel := PanelContainer.new()
	var dialogue := _box(PAPER, LAMP, 0)
	dialogue.border_width_left = 4
	panel.add_theme_stylebox_override("panel", dialogue)
	content.add_child(panel)
	var text_column := VBoxContainer.new()
	text_column.add_theme_constant_override("separation", 14)
	panel.add_child(text_column)
	_speaker = Label.new()
	_speaker.add_theme_color_override("font_color", SLATE)
	_speaker.add_theme_font_size_override("font_size", 15)
	_speaker.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	text_column.add_child(_speaker)
	_text = RichTextLabel.new()
	_text.bbcode_enabled = false
	_text.fit_content = true
	_text.scroll_active = false
	_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_text.add_theme_color_override("default_color", INK)
	_text.add_theme_font_override("normal_font", DisplayFont)
	_text.custom_minimum_size.y = 80
	text_column.add_child(_text)
	_choices = VBoxContainer.new()
	_choices.add_theme_constant_override("separation", 10)
	content.add_child(_choices)


func _texture(id: Variant) -> Texture2D:
	if id == null or not _assets.has(id):
		return null
	var image := Image.new()
	if image.load_png_from_buffer(_assets[id]) != OK:
		return null
	return ImageTexture.create_from_image(image)


func _render() -> void:
	var current: Dictionary = _player.view
	_speaker.text = current["speaker_name"] if current["speaker_name"] != null else ("The end" if current["type"] == "end" else "")
	_speaker.visible = _speaker.text != ""
	_text.text = current["text"]
	if _last_background != current["background"]:
		_background.texture = null
		_background.texture = _texture(current["background"])
		_last_background = current["background"]
	if _last_portrait != current["portrait"]:
		_portrait.texture = null
		_portrait.texture = _texture(current["portrait"])
		_last_portrait = current["portrait"]
	_stage.visible = current["background"] != null or current["portrait"] != null
	for child in _choices.get_children():
		_choices.remove_child(child)
		child.queue_free()
	_buttons.clear()
	var generation: int = _player.generation
	if current["type"] == "line":
		_add_action("Continue", "advance", generation)
	elif current["type"] == "choice":
		for index in range(current["options"].size()):
			var option: Dictionary = current["options"][index]
			_add_action(str(index + 1) + ".  " + option["text"], "choose:" + option["id"], generation)
	_scroll.scroll_vertical = 0
	if not _buttons.is_empty():
		_buttons[0].call_deferred("grab_focus")
	_publish_qa.call_deferred()


func _add_action(label: String, action: String, generation: int) -> void:
	var button := _button(label, true)
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	button.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	button.custom_minimum_size.y = 58
	button.add_theme_font_size_override("font_size", 18)
	button.pressed.connect(_action.bind(action, generation, _player))
	_choices.add_child(button)
	_buttons.append(button)


func _action(action: String, generation: int, session: RefCounted) -> void:
	if session == _player and _player.act(action, generation) == "":
		_notice.text = ""
		_render()


func _save_path() -> String:
	return SaveStore.path_for(_hash)


func _toolbar(action: String) -> void:
	if action == "Restart":
		_player = PlayerScript.new(_source, _hash)
		_notice.text = "Started over. Your saved game is still available."
		_render()
	elif action == "Save":
		var error: String = SaveStore.write_save(_hash, _player.save())
		_notice.text = "Saved on this device." if error == "" else "This device could not save your progress. Your previous save is unchanged."
		if error == "" and OS.has_feature("web") and not OS.is_userfs_persistent():
			_notice.text = "Saved for this session. Browser storage is unavailable."
		_publish_qa.call_deferred()
	elif action == "Load":
		var saved: Dictionary = SaveStore.read_save(_hash)
		if saved.get("error") == "not_found":
			_notice.text = "No saved game on this device yet."
			_publish_qa.call_deferred()
			return
		if saved.get("error", "save_read_failed") != "":
			_notice.text = "That saved game cannot be loaded. Your progress is unchanged."
			_publish_qa.call_deferred()
			return
		var error: String = _player.load_save(saved["data"])
		if error != "":
			_notice.text = "That saved game cannot be loaded. Your progress is unchanged."
			_publish_qa.call_deferred()
			return
		_notice.text = "Saved game loaded."
		_render()


func _resize_layout() -> void:
	var compact := size.x < 600
	var padding := 16 if compact else 32
	for side: String in ["left", "right", "top", "bottom"]:
		_margin.add_theme_constant_override("margin_" + side, padding)
	_title.add_theme_font_size_override("font_size", 26 if compact else 34)
	_text.add_theme_font_size_override("normal_font_size", 20 if compact else 24)
	_stage.custom_minimum_size.y = 160 if compact else 230
	_publish_qa.call_deferred()


func _unhandled_key_input(event: InputEvent) -> void:
	if not event is InputEventKey or not event.pressed or event.echo or event.ctrl_pressed or event.meta_pressed or event.alt_pressed:
		return
	var current: Dictionary = _player.view
	var action := ""
	if current["type"] == "line" and event.keycode in [KEY_ENTER, KEY_SPACE]:
		action = "advance"
	elif current["type"] == "choice" and event.keycode >= KEY_1 and event.keycode <= KEY_9:
		var index: int = event.keycode - KEY_1
		if index < current["options"].size():
			action = "choose:" + current["options"][index]["id"]
	if action != "":
		_action(action, _player.generation, _player)
		get_viewport().set_input_as_handled()


func _publish_qa() -> void:
	if not _qa:
		return
	await get_tree().process_frame
	var controls: Array = []
	for button: Button in _buttons:
		var rectangle := button.get_global_rect()
		controls.append({"label": button.text, "x": rectangle.position.x, "y": rectangle.position.y,
			"width": rectangle.size.x, "height": rectangle.size.y})
	var snapshot := {"node_id": _player.state["node_id"], "status": _player.state["status"],
		"ending": _player.state["ending"], "fault": _player.state["fault"], "view": _player.view,
		"has_save": FileAccess.file_exists(_save_path()), "viewport": {"width": size.x, "height": size.y},
		"controls": controls, "notice": _notice.text}
	var browser: Variant = JavaScriptBridge.get_interface("window")
	var json: Variant = JavaScriptBridge.get_interface("JSON")
	if browser != null and json != null:
		browser.__flintNarrativeQA = json.parse(JSON.stringify(snapshot))
