# SPDX-License-Identifier: MIT
# Visual novel layout for story format 2 (ADR 0040): a full-screen stage, characters in
# three slots standing on the bottom edge, and a themed text box. Story strings render
# as plain text; images and fonts come only from verified package bytes.
extends Control

const PlayerScript = preload("res://runtime/player.gd")
const SaveStore = preload("res://runtime/save_store.gd")
const DisplayFont = preload("res://fonts/Lora.ttf")
const INK := Color("182635")
const PAPER := Color("f0f4f6")
const LAMP := Color("d5ae68")
const SLOTS := {"left": 0.2, "center": 0.5, "right": 0.8}
# Theme defaults from the design review; every theme field is optional.
const DEFAULTS := {
	"textbox": {"position": "bottom", "width": 92, "background": "#182635e6",
		"text": "#f0f4f6", "border": "#d5ae68", "radius": 12},
	"name": {"show": true, "background": "#d5ae68", "text": "#182635"},
	"choices": {"background": "#f0f4f6", "text": "#182635", "border": "#d5ae68"},
	"font": {"asset": null, "size": 22},
}
var _source: Dictionary
var _hash: String
var _assets: Dictionary
var _theme: Dictionary
var _font: Font
var _player: RefCounted
var _background: TextureRect
var _figures: Control
var _sprites: Dictionary = {}
var _textures: Dictionary = {}
var _box: PanelContainer
var _name_box: PanelContainer
var _name: Label
var _text: RichTextLabel
var _continue: Button
var _choices: VBoxContainer
var _menu: HBoxContainer
var _notice: Label
var _buttons: Array[Button] = []
var _qa := false


func configure(source: Dictionary, package_hash: String, assets: Dictionary) -> void:
	_source = source
	_hash = package_hash
	_assets = assets.duplicate()
	_theme = _merged(source.get("theme", {}))
	_font = _story_font()
	_player = PlayerScript.new(source, package_hash)
	_build()
	resized.connect(_layout)
	_render()
	if OS.has_feature("web"):
		var browser: Variant = JavaScriptBridge.get_interface("window")
		if browser != null:
			var query: Variant = browser.location.search
			if query is String:
				_qa = query.trim_prefix("?").split("&").has("qa=1")
		_publish_qa.call_deferred()


func _merged(theme: Dictionary) -> Dictionary:
	var merged := DEFAULTS.duplicate(true)
	for part: String in theme:
		for key: String in theme[part]:
			merged[part][key] = theme[part][key]
	return merged


func _story_font() -> Font:
	var id: Variant = _theme["font"]["asset"]
	if id == null or not _assets.has(id):
		return DisplayFont
	var font := FontFile.new()
	font.data = _assets[id]
	font.fallbacks = [DisplayFont]  # Glyphs the creator's font lacks still render.
	return font


func _color(value: String) -> Color:
	return Color.html(value)


func _style(fill: Color, border: Color, radius: int, width: int = 2) -> StyleBoxFlat:
	var box := StyleBoxFlat.new()
	box.bg_color = fill
	box.border_color = border
	box.set_border_width_all(width)
	box.set_corner_radius_all(radius)
	box.content_margin_left = 22
	box.content_margin_right = 22
	box.content_margin_top = 14
	box.content_margin_bottom = 14
	return box


func _small_button(label: String) -> Button:
	var button := Button.new()
	button.text = label
	button.focus_mode = Control.FOCUS_ALL
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.add_theme_font_size_override("font_size", 14)
	for role: String in ["font_color", "font_hover_color", "font_focus_color", "font_pressed_color"]:
		button.add_theme_color_override(role, PAPER)
	var normal := _style(Color(INK, 0.72), Color(PAPER, 0.35), 8, 1)
	for side: String in ["left", "right"]:
		normal.set("content_margin_" + side, 12)
	for side: String in ["top", "bottom"]:
		normal.set("content_margin_" + side, 6)
	button.add_theme_stylebox_override("normal", normal)
	var hover := normal.duplicate()
	hover.border_color = LAMP
	button.add_theme_stylebox_override("hover", hover)
	button.add_theme_stylebox_override("pressed", hover)
	var focus := normal.duplicate()
	focus.bg_color = Color.TRANSPARENT
	focus.border_color = LAMP
	focus.set_border_width_all(3)
	button.add_theme_stylebox_override("focus", focus)
	return button


func _build() -> void:
	var ground := ColorRect.new()
	ground.color = INK
	ground.mouse_filter = Control.MOUSE_FILTER_IGNORE
	ground.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(ground)
	_background = TextureRect.new()
	_background.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_background.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	_background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_background)
	_figures = Control.new()
	_figures.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_figures.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_figures)
	var box: Dictionary = _theme["textbox"]
	_box = PanelContainer.new()
	_box.mouse_filter = Control.MOUSE_FILTER_PASS  # A click on the text box advances too.
	_box.add_theme_stylebox_override("panel", _style(_color(box["background"]), _color(box["border"]), box["radius"]))
	add_child(_box)
	var column := VBoxContainer.new()
	column.mouse_filter = Control.MOUSE_FILTER_PASS
	column.add_theme_constant_override("separation", 8)
	_box.add_child(column)
	_name_box = PanelContainer.new()
	_name_box.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	column.add_child(_name_box)
	_name = Label.new()
	_name.add_theme_font_override("font", _font)
	_name_box.add_child(_name)
	_text = RichTextLabel.new()
	_text.mouse_filter = Control.MOUSE_FILTER_PASS
	_text.bbcode_enabled = false
	_text.fit_content = true
	_text.scroll_active = false
	_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_text.add_theme_font_override("normal_font", _font)
	_text.add_theme_color_override("default_color", _color(box["text"]))
	column.add_child(_text)
	_continue = _small_button("Continue")
	_continue.size_flags_horizontal = Control.SIZE_SHRINK_END
	_continue.pressed.connect(func() -> void: _action("advance", _player.generation, _player))
	column.add_child(_continue)
	_choices = VBoxContainer.new()
	_choices.add_theme_constant_override("separation", 12)
	add_child(_choices)
	_menu = HBoxContainer.new()
	_menu.add_theme_constant_override("separation", 6)
	_anchored(_menu, 1.0, 1.0, 0.0, 0.0)
	_menu.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	_menu.offset_right = -12
	_menu.offset_top = 12
	add_child(_menu)
	for item: String in ["Save", "Load", "Restart"]:
		var button := _small_button(item)
		button.pressed.connect(_toolbar.bind(item))
		_menu.add_child(button)
	_notice = Label.new()
	_anchored(_notice, 0.55, 1.0, 0.0, 0.0)
	_notice.offset_right = -12
	_notice.offset_top = 56
	_notice.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	_notice.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_notice.add_theme_color_override("font_color", PAPER)
	_notice.add_theme_color_override("font_outline_color", INK)
	_notice.add_theme_constant_override("outline_size", 4)
	_notice.add_theme_font_size_override("font_size", 14)
	add_child(_notice)


func _texture(id: Variant) -> Texture2D:
	if id == null or not _assets.has(id):
		return null
	if not _textures.has(id):
		var image := Image.new()
		if image.load_png_from_buffer(_assets[id]) != OK:
			return null
		_textures[id] = ImageTexture.create_from_image(image)
	return _textures[id]


func _render() -> void:
	var current: Dictionary = _player.view
	var stage: Dictionary = current["stage"]
	var in_use := {}
	_background.texture = _texture(stage["background"])
	if stage["background"] != null:
		in_use[stage["background"]] = true
	var shown := {}
	for item: Dictionary in stage["characters"]:
		var id: String = item["id"]
		var asset: String = _source["characters"][id]["sprites"][item["sprite"]]
		in_use[asset] = true
		if not _sprites.has(id):
			var figure := TextureRect.new()
			figure.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
			figure.stretch_mode = TextureRect.STRETCH_SCALE
			figure.mouse_filter = Control.MOUSE_FILTER_IGNORE
			_figures.add_child(figure)
			_sprites[id] = figure
		_sprites[id].texture = _texture(asset)
		_sprites[id].set_meta("position", item["position"])
		shown[id] = true
	for id: String in _sprites.keys():
		if not shown.has(id):
			_sprites[id].queue_free()
			_sprites.erase(id)
	for id: String in _textures.keys():
		if not in_use.has(id):
			_textures.erase(id)  # Only what is on screen stays decoded.
	var named: Dictionary = _theme["name"]
	var speaker: Variant = current["speaker_name"]
	_name.text = speaker if speaker != null else ""
	_name_box.visible = named["show"] and speaker != null
	var fill := _color(named["background"])
	var ink := _color(named["text"])
	if current["speaker_color"] != null:
		fill = _color(current["speaker_color"])
		ink = INK if fill.get_luminance() > 0.5 else PAPER
	var tag := _style(fill, fill, maxi(4, int(_theme["textbox"]["radius"] / 2.0)), 0)
	tag.content_margin_top = 4
	tag.content_margin_bottom = 4
	tag.content_margin_left = 14
	tag.content_margin_right = 14
	_name_box.add_theme_stylebox_override("panel", tag)
	_name.add_theme_color_override("font_color", ink)
	_text.text = current["text"]
	_continue.visible = current["type"] == "line"
	for child in _choices.get_children():
		_choices.remove_child(child)
		child.queue_free()
	_buttons.clear()
	var generation: int = _player.generation
	if current["type"] == "line":
		_buttons.append(_continue)
	elif current["type"] == "choice":
		for index in range(current["options"].size()):
			var option: Dictionary = current["options"][index]
			_add_choice(option["text"], "choose:" + option["id"], generation)
	elif current["type"] in ["end", "fault"]:
		var again := _choice_button("Play again")
		again.pressed.connect(_toolbar.bind("Restart"))
		_choices.add_child(again)
		_buttons.append(again)
	_layout()
	if not _buttons.is_empty():
		_buttons[0].call_deferred("grab_focus")
	_publish_qa.call_deferred()


func _choice_button(label: String) -> Button:
	var palette: Dictionary = _theme["choices"]
	var radius: int = _theme["textbox"]["radius"]
	var button := Button.new()
	button.text = label
	button.focus_mode = Control.FOCUS_ALL
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	button.custom_minimum_size.y = 52
	button.add_theme_font_override("font", _font)
	for role: String in ["font_color", "font_hover_color", "font_focus_color", "font_pressed_color"]:
		button.add_theme_color_override(role, _color(palette["text"]))
	var normal := _style(_color(palette["background"]), _color(palette["border"]), radius)
	button.add_theme_stylebox_override("normal", normal)
	var hover := normal.duplicate()
	hover.set_border_width_all(3)
	button.add_theme_stylebox_override("hover", hover)
	button.add_theme_stylebox_override("pressed", hover)
	var focus := normal.duplicate()
	focus.bg_color = Color.TRANSPARENT
	focus.set_border_width_all(4)
	button.add_theme_stylebox_override("focus", focus)
	return button


func _add_choice(label: String, action: String, generation: int) -> void:
	var button := _choice_button(label)
	button.pressed.connect(_action.bind(action, generation, _player))
	_choices.add_child(button)
	_buttons.append(button)


func _anchored(control: Control, left: float, right: float, top: float, bottom: float) -> void:
	control.anchor_left = left
	control.anchor_right = right
	control.anchor_top = top
	control.anchor_bottom = bottom


func _layout() -> void:
	if size.x <= 0 or size.y <= 0:
		return
	var scale_factor := clampf(minf(size.x / 1280.0, size.y / 720.0), 0.6, 1.6)
	var font_size := int(round(int(_theme["font"]["size"]) * scale_factor))
	_text.add_theme_font_size_override("normal_font_size", font_size)
	_name.add_theme_font_size_override("font_size", maxi(12, int(font_size * 0.8)))
	for button: Button in _buttons:
		if button != _continue:
			button.add_theme_font_size_override("font_size", font_size)
	var margin := 24.0 * scale_factor
	# The text box: theme width, centred, growing away from its edge as text wraps.
	var box: Dictionary = _theme["textbox"]
	var half := float(box["width"]) / 200.0
	var where: String = box["position"]
	var edge: float = {"bottom": 1.0, "top": 0.0, "middle": 0.5}[where]
	_anchored(_box, 0.5 - half, 0.5 + half, edge, edge)
	_box.offset_left = 0
	_box.offset_right = 0
	_box.custom_minimum_size = Vector2(0, font_size * 4.2)
	_box.grow_vertical = {"bottom": Control.GROW_DIRECTION_BEGIN, "top": Control.GROW_DIRECTION_END,
		"middle": Control.GROW_DIRECTION_BOTH}[where]
	_box.offset_top = margin + 44.0 * scale_factor if where == "top" else 0.0
	_box.offset_bottom = -margin if where == "bottom" else _box.offset_top
	# Choices sit centred in the space the text box leaves free.
	var choice_half := minf(size.x - 2.0 * margin, 620.0 * scale_factor) / 2.0 / size.x
	var at: float = {"bottom": 0.4, "top": 0.66, "middle": 0.82}[where]
	_anchored(_choices, 0.5 - choice_half, 0.5 + choice_half, at, at)
	_choices.offset_left = 0
	_choices.offset_right = 0
	_choices.offset_top = 0
	_choices.offset_bottom = 0
	_choices.grow_vertical = Control.GROW_DIRECTION_BOTH
	# Characters keep their aspect, stand on the bottom edge and fill most of the height.
	var slot_width := size.x * 0.36
	var slot_height := size.y * 0.92
	for id: String in _sprites:
		var figure: TextureRect = _sprites[id]
		var texture := figure.texture
		if texture == null:
			figure.size = Vector2.ZERO
			continue
		var natural := Vector2(texture.get_width(), texture.get_height())
		var factor := minf(slot_width / natural.x, slot_height / natural.y)
		var drawn := natural * factor
		var center: float = SLOTS[figure.get_meta("position")] * size.x
		figure.position = Vector2(center - drawn.x / 2.0, size.y - drawn.y)
		figure.size = drawn
	_publish_qa.call_deferred()


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
		if _player.load_save(saved["data"]) != "":
			_notice.text = "That saved game cannot be loaded. Your progress is unchanged."
			_publish_qa.call_deferred()
			return
		_notice.text = "Saved game loaded."
		_render()


func _gui_input(event: InputEvent) -> void:
	# Clicking or tapping the stage advances a line, as in most visual novels.
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		if _player.view["type"] == "line":
			_action("advance", _player.generation, _player)
			accept_event()


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


func _rect(control: Control) -> Dictionary:
	var rectangle := control.get_global_rect()
	return {"x": rectangle.position.x, "y": rectangle.position.y,
		"width": rectangle.size.x, "height": rectangle.size.y}


func _publish_qa() -> void:
	if not _qa:
		return
	await get_tree().process_frame
	var controls: Array = []
	for button: Button in _buttons:
		controls.append(_rect(button).merged({"label": button.text}))
	var figures: Array = []
	for id: String in _sprites:
		figures.append(_rect(_sprites[id]).merged({"id": id, "loaded": _sprites[id].texture != null}))
	var snapshot := {"node_id": _player.state["node_id"], "status": _player.state["status"],
		"ending": _player.state["ending"], "fault": _player.state["fault"], "view": _player.view,
		"has_save": FileAccess.file_exists(_save_path()), "viewport": {"width": size.x, "height": size.y},
		"controls": controls, "notice": _notice.text, "layout": "stage",
		"textbox": _rect(_box), "name_visible": _name_box.visible, "figures": figures,
		"background_loaded": _background.texture != null, "custom_font": _font != DisplayFont}
	var browser: Variant = JavaScriptBridge.get_interface("window")
	var json: Variant = JavaScriptBridge.get_interface("JSON")
	if browser != null and json != null:
		browser.__flintNarrativeQA = json.parse(JSON.stringify(snapshot))
