# SPDX-License-Identifier: MIT
# Visual novel layout for story format 2 (ADR 0040): a full-screen stage, characters in
# three slots standing on the bottom edge, and a themed text box. Story strings render
# as plain text; images and fonts come only from verified package bytes.
extends Control

const PlayerScript = preload("res://runtime/player.gd")
const SaveStore = preload("res://runtime/save_store.gd")
const PlayerTerms = preload("res://runtime/player_terms.gd")
const Reading = preload("res://runtime/reading.gd")
const SoundChannel = preload("res://runtime/sound_channel.gd")
const DisplayFont = preload("res://fonts/Lora.ttf")
const INK := Color("182635")
const PAPER := Color("f0f4f6")
const LAMP := Color("d5ae68")
const SLOTS := {"left": 0.2, "center": 0.5, "right": 0.8}
const DIMMED := Color(0.56, 0.56, 0.62)
const TOOLTIPS := {"Log": "Read earlier lines (L)", "Auto": "Advance by itself (A)",
	"Skip": "Skip lines you have read (S)", "Hide": "Hide the interface (H)", "Menu": "Saves and settings (Esc)"}
# Theme defaults from the design review; every theme field is optional.
const DEFAULTS := {
	"textbox": {"position": "bottom", "width": 92, "background": "#182635e6",
		"text": "#f0f4f6", "border": "#d5ae68", "radius": 12},
	"name": {"show": true, "background": "#d5ae68", "text": "#182635"},
	"choices": {"background": "#f0f4f6", "text": "#182635", "border": "#d5ae68"},
	"font": {"asset": null, "size": 22},
	"title": {"background": null, "music": null},
}
var _source: Dictionary
var _hash: String
var _assets: Dictionary
var _theme: Dictionary
var _font: Font
var _player: RefCounted
var _background: TextureRect
var _cg: TextureRect
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
var _gallery_panel: PanelContainer
var _gallery_image: TextureRect
var _gallery_entries: VBoxContainer
var _gallery_saved: Array = []
var _gallery_disabled: Dictionary = {}
var _advance_key: int = 0
# Voice clips (ADR 0043): played when a line settles, stopped on the next screen.
var _voice_player: AudioStreamPlayer
var _voice_streams: Dictionary = {}
var _voice_generation := -1
var _voice_session: RefCounted
var _voice_volume := 100
var _volume_slider: HSlider
# Browsers keep sound off until the first click or key press. Where a page may not
# start sound yet, that input opens a start screen instead of skipping the first line.
var _sound_gate: Control
# Terms a voice model license puts on players (ADR 0045): shown once before play and
# again from the menu. Until they are accepted the story does not start or speak.
var _terms: Variant = null
var _terms_panel: PanelContainer
var _terms_button: Button
var _terms_required := false
var _terms_disabled: Dictionary = {}
# Player controls (ADR 0064). None of them changes story state.
var _settings: Dictionary
var _screen_generation := -1
var _screen_session: RefCounted
var _reveal_total := 0.0
var _reveal_elapsed := 0.0
var _auto := false
var _skip := false
var _wait := 0.0
var _ui_hidden := false
var _backlog: Array = []
var _read: Dictionary = {}
var _read_dirty := false
var _read_flush := 0.0
var _auto_button: Button
var _skip_button: Button
var _log_panel: PanelContainer
var _log_scroll: ScrollContainer
var _log_entries: VBoxContainer
var _log_close: Button
var _log_disabled: Dictionary = {}
var _menu_panel: PanelContainer
var _menu_close: Button
var _menu_buttons: Array[Button] = []
var _menu_disabled: Dictionary = {}
var _speed_buttons: Dictionary = {}
var _auto_speed_buttons: Dictionary = {}
var _focus_toggle: CheckButton
var _motion_toggle: CheckButton
# Transitions and effects (ADR 0065): the old screen stays above the new one until it
# has gone, so the stage underneath is always the settled one.
var _stage_root: Control
var _leaving: Control
var _curtain: ColorRect
var _flash: ColorRect
var _last_stage: Variant = null
var _fx_kind := ""
var _fx_elapsed := 0.0
var _fx_total := 0.0
var _pending_effect: Variant = null
var _effect_kind := ""
var _effect_elapsed := 0.0
# Music, ambience and sound effects (ADR 0066).
var _music: RefCounted
var _ambience: RefCounted
var _effects_player: AudioStreamPlayer
var _tracks: Dictionary = {}
var _mute_toggle: CheckButton
# The title screen (ADR 0071): only when the theme gives it art or music.
var _title_panel: Control
var _title_art: TextureRect
var _title_heading: Label
var _title_status: Label
var _title_buttons: Dictionary = {}
var _story_menu_buttons: Dictionary = {}  # Each button, and whether it starts out disabled.
var _started := false
var _name_field: LineEdit  # While the story asks for the player's name (ADR 0072).


func configure(source: Dictionary, package_hash: String, assets: Dictionary, notices: String = "") -> void:
	_terms = PlayerTerms.parse(notices).get("terms")
	_source = source
	_hash = package_hash
	_assets = assets.duplicate()
	_theme = _merged(source.get("theme", {}))
	_font = _story_font()
	_gallery_saved = _read_gallery()
	_settings = _read_settings()
	if not _settings_saved() and _browser_wants_less_motion():
		_settings["reduced_motion"] = true
	_voice_volume = _settings["voice_volume"]
	_read = _read_marks()
	_player = PlayerScript.new(source, package_hash, _gallery_saved)
	_build()
	if _terms != null:
		_build_terms()
		if _read_terms() != _digest(_terms):
			_open_terms(true)
	if _has_sound():
		# Deferred: playtests configure inside the browser callback that delivers the
		# story, where the probe cannot run. It still runs before the first clip starts.
		_gate_sound.call_deferred()
	resized.connect(_layout)
	if _wants_title():
		_show_title()
	else:
		_started = true
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


func _small_toggle(label: String) -> Button:
	# Lit while on, so a mode that is running shows at a glance.
	var button := _small_button(label)
	button.toggle_mode = true
	var lit: StyleBoxFlat = button.get_theme_stylebox("normal").duplicate()
	lit.bg_color = LAMP
	lit.border_color = LAMP
	button.add_theme_stylebox_override("pressed", lit)
	for role: String in ["font_pressed_color", "font_hover_pressed_color"]:
		button.add_theme_color_override(role, INK)
	return button


func _build() -> void:
	var ground := ColorRect.new()
	ground.color = INK
	ground.mouse_filter = Control.MOUSE_FILTER_IGNORE
	ground.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(ground)
	_stage_root = Control.new()  # What a shake moves: everything but the text and controls.
	_stage_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_stage_root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_stage_root)
	_background = TextureRect.new()
	_background.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_background.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	_background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_stage_root.add_child(_background)
	_figures = Control.new()
	_figures.clip_contents = true  # Framed figures continue below the screen edge.
	_figures.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_figures.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_stage_root.add_child(_figures)
	_cg = TextureRect.new()
	_cg.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_cg.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	_cg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_cg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_stage_root.add_child(_cg)  # Over the stage; text, choices and controls are drawn above it.
	_curtain = _cover(Color(0, 0, 0, 0))
	_flash = _cover(Color(1, 1, 1, 0))
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
	_text.visible_characters_behavior = TextServer.VC_CHARS_AFTER_SHAPING  # Words never jump lines.
	_text.add_theme_color_override("default_color", _color(box["text"]))
	column.add_child(_text)
	_continue = _small_button("Continue")
	_continue.size_flags_horizontal = Control.SIZE_SHRINK_END
	_continue.pressed.connect(_request_advance)
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
	for item: String in ["Log", "Auto", "Skip", "Hide", "Menu"]:
		var button := _small_toggle(item) if item in ["Auto", "Skip"] else _small_button(item)
		button.tooltip_text = TOOLTIPS[item]
		button.pressed.connect(_toolbar.bind(item))
		_menu.add_child(button)
		if item == "Auto":
			_auto_button = button
		elif item == "Skip":
			_skip_button = button
	_voice_player = AudioStreamPlayer.new()
	add_child(_voice_player)
	_effects_player = AudioStreamPlayer.new()
	add_child(_effects_player)
	_music = SoundChannel.new(self)
	_ambience = SoundChannel.new(self)
	_apply_volume()
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
	if _wants_title():
		_build_title()
	_build_log()
	_build_menu_panel()
	_build_gallery()


func _wants_title() -> bool:
	return _theme["title"]["background"] != null or _theme["title"]["music"] != null


func _title_showing() -> bool:
	return _title_panel != null and _title_panel.visible


func _build_title() -> void:
	_title_panel = Control.new()
	_title_panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_title_panel.mouse_filter = Control.MOUSE_FILTER_STOP
	_title_panel.hide()
	add_child(_title_panel)
	var ground := ColorRect.new()
	ground.color = INK
	ground.mouse_filter = Control.MOUSE_FILTER_IGNORE
	ground.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_title_panel.add_child(ground)
	_title_art = TextureRect.new()
	_title_art.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_title_art.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	_title_art.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_title_art.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_title_panel.add_child(_title_art)
	var margin := MarginContainer.new()
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	margin.mouse_filter = Control.MOUSE_FILTER_IGNORE
	for side: String in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 24)
	_title_panel.add_child(margin)
	var column := VBoxContainer.new()
	column.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_theme_constant_override("separation", 12)
	margin.add_child(column)
	_title_heading = Label.new()
	_title_heading.text = _source["title"]  # A Label shows story text as plain text.
	_title_heading.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_title_heading.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_title_heading.add_theme_font_override("font", _font)
	_title_heading.add_theme_color_override("font_color", PAPER)
	_title_heading.add_theme_color_override("font_outline_color", INK)
	_title_heading.add_theme_constant_override("outline_size", 12)
	column.add_child(_title_heading)
	var spacer := Control.new()
	spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(spacer)
	_title_status = Label.new()
	_title_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_title_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_title_status.add_theme_color_override("font_color", PAPER)
	_title_status.add_theme_color_override("font_outline_color", INK)
	_title_status.add_theme_constant_override("outline_size", 4)
	column.add_child(_title_status)
	for item: String in ["Start", "Continue", "Gallery", "Settings", "Quit"]:
		var button := _choice_button(item)
		button.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
		button.pressed.connect(_title_action.bind(item))
		column.add_child(button)
		_title_buttons[item] = button


func _show_title() -> void:
	_set_auto(false)
	_set_skip(false)
	_voice_player.stop()
	for control: Control in [_box, _choices, _menu, _notice]:
		control.hide()  # Out of reach of the keyboard as well as out of sight.
	_title_art.texture = _texture(_theme["title"]["background"])
	_title_status.text = ""
	_title_buttons["Continue"].visible = _has_saved_game()
	_title_buttons["Gallery"].visible = not _player.gallery.is_empty()
	_title_buttons["Quit"].visible = not OS.has_feature("web")
	_title_panel.show()
	_layout()
	_title_buttons["Start"].call_deferred("grab_focus")
	_play_title_music.call_deferred()
	_publish_qa.call_deferred()


func _has_saved_game() -> bool:
	return SaveStore.read_save(_hash).get("error") != "not_found"


func _leave_title() -> void:
	_title_panel.hide()
	_title_art.texture = null
	for control: Control in [_box, _choices, _menu, _notice]:
		control.show()
	_notice.text = ""


func _play_title_music() -> void:
	if not _title_showing() or not _sound_allowed():
		return
	var id: Variant = _theme["title"]["music"]
	_music.change(id, _track(id), false)
	_ambience.change(null, null, false)


func _title_action(action: String) -> void:
	if action == "Start":
		_leave_title()
		if _started:
			_toolbar("Restart")
			_notice.text = ""
		else:
			_started = true
			_render()
	elif action == "Continue":
		var saved: Dictionary = SaveStore.read_save(_hash)
		if _load_slot(saved, "No saved game on this device yet.", "Saved game loaded."):
			var loaded: String = _notice.text
			_started = true
			_leave_title()
			_notice.text = loaded
			_refocus()
		else:
			_title_status.text = _notice.text
	elif action == "Gallery":
		_toolbar("Gallery")
	elif action == "Settings":
		_toolbar("Menu")
	elif action == "Quit":
		get_tree().quit()


func _panel_label(text: String, size_px: int = 14) -> Label:
	var label := Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_color_override("font_color", PAPER)
	label.add_theme_font_size_override("font_size", size_px)
	return label


func _build_log() -> void:
	_log_panel = PanelContainer.new()
	_log_panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_log_panel.mouse_filter = Control.MOUSE_FILTER_STOP
	_log_panel.add_theme_stylebox_override("panel", _style(Color(INK, 0.96), LAMP, 0))
	_log_panel.hide()
	add_child(_log_panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 12)
	_log_panel.add_child(column)
	_log_close = _small_button("Close log")
	_log_close.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	_log_close.pressed.connect(_close_log)
	column.add_child(_log_close)
	_log_scroll = ScrollContainer.new()
	_log_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_log_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	column.add_child(_log_scroll)
	_log_entries = VBoxContainer.new()
	_log_entries.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_log_entries.add_theme_constant_override("separation", 10)
	_log_scroll.add_child(_log_entries)


func _note_backlog(speaker: Variant, text: String, color: Variant = null) -> void:
	_backlog.append({"speaker": speaker, "text": text, "color": color})
	while _backlog.size() > Reading.BACKLOG_LIMIT:
		_backlog.pop_front()


func backlog_rows() -> Array:
	var rows: Array = []
	for entry: Dictionary in _backlog:
		rows.append([entry["speaker"], entry["text"]])
	return rows


func _open_log() -> void:
	if _overlay_open():
		return
	for child in _log_entries.get_children():
		_log_entries.remove_child(child)
		child.queue_free()
	if _backlog.is_empty():
		_log_entries.add_child(_panel_label("Nothing here yet.", 18))
	for entry: Dictionary in _backlog:
		# Labels draw plain text, so story markup can never become formatting here.
		var row := VBoxContainer.new()
		row.add_theme_constant_override("separation", 2)
		if entry["speaker"] != null:
			var speaker := _panel_label(entry["speaker"])
			speaker.add_theme_color_override("font_color", _color(entry["color"]) if entry["color"] != null else LAMP)
			row.add_child(speaker)
		var body := _panel_label(entry["text"], 18)
		body.add_theme_font_override("font", _font)
		row.add_child(body)
		_log_entries.add_child(row)
	_pause_controls(_log_disabled)
	_log_panel.show()
	_log_close.grab_focus()
	_overlay_changed()
	_scroll_log_to_end.call_deferred()
	_publish_qa.call_deferred()


func _scroll_log_to_end() -> void:
	if is_inside_tree():
		await get_tree().process_frame
		_log_scroll.scroll_vertical = int(_log_scroll.get_v_scroll_bar().max_value)


func _close_log() -> void:
	if not _log_panel.visible:
		return
	_log_panel.hide()
	_resume_controls(_log_disabled)
	_refocus()
	_overlay_changed()
	_publish_qa.call_deferred()


func _build_menu_panel() -> void:
	_menu_panel = PanelContainer.new()
	_menu_panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_menu_panel.mouse_filter = Control.MOUSE_FILTER_STOP
	_menu_panel.add_theme_stylebox_override("panel", _style(Color(INK, 0.96), LAMP, 0))
	_menu_panel.hide()
	add_child(_menu_panel)
	var scroll := ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_menu_panel.add_child(scroll)
	var column := VBoxContainer.new()
	column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	column.add_theme_constant_override("separation", 10)
	scroll.add_child(column)
	_menu_close = _small_button("Close menu")
	_menu_close.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	_menu_close.pressed.connect(_close_menu)
	column.add_child(_menu_close)
	column.add_child(_panel_label("Game"))
	var actions := HFlowContainer.new()
	actions.add_theme_constant_override("h_separation", 6)
	actions.add_theme_constant_override("v_separation", 6)
	column.add_child(actions)
	var story_items: Array[String] = ["Save", "Load", "Quick save", "Quick load", "Restart"]
	if _wants_title():
		story_items.append("Title screen")
	for item: String in story_items + ["Gallery"] + (["License"] if _terms != null else []):
		var button := _small_button(item)
		button.pressed.connect(_toolbar.bind(item))
		actions.add_child(button)
		_menu_buttons.append(button)
		if item in story_items:
			_story_menu_buttons[button] = button.disabled
	_speed_buttons = _setting_row(column, "Text speed", Reading.TEXT_SPEEDS.keys(), _settings["text_speed"], _set_text_speed)
	_auto_speed_buttons = _setting_row(column, "Auto speed", Reading.AUTO_SPEEDS.keys(), _settings["auto_speed"], _set_auto_speed)
	_volume_slider = _volume_row(column, "Voice volume", _voice_volume, _set_volume)
	_volume_row(column, "Music volume", _settings["music_volume"], _set_channel_volume.bind("music_volume"))
	_volume_row(column, "Ambience volume", _settings["ambience_volume"], _set_channel_volume.bind("ambience_volume"))
	_volume_row(column, "Sound effects volume", _settings["effects_volume"], _set_channel_volume.bind("effects_volume"))
	_mute_toggle = CheckButton.new()
	_mute_toggle.text = "Mute all sound"
	_mute_toggle.focus_mode = Control.FOCUS_ALL
	_mute_toggle.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	for role: String in ["font_color", "font_pressed_color", "font_hover_color", "font_hover_pressed_color", "font_focus_color"]:
		_mute_toggle.add_theme_color_override(role, PAPER)
	_mute_toggle.add_theme_font_size_override("font_size", 14)
	_mute_toggle.set_pressed_no_signal(_settings["muted"])
	_mute_toggle.toggled.connect(_set_muted)
	column.add_child(_mute_toggle)
	_focus_toggle = CheckButton.new()
	_focus_toggle.text = "Dim characters who are not speaking"
	_focus_toggle.focus_mode = Control.FOCUS_ALL
	_focus_toggle.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	_focus_toggle.add_theme_color_override("font_color", PAPER)
	_focus_toggle.add_theme_color_override("font_pressed_color", PAPER)
	_focus_toggle.add_theme_color_override("font_hover_color", PAPER)
	_focus_toggle.add_theme_color_override("font_hover_pressed_color", PAPER)
	_focus_toggle.add_theme_color_override("font_focus_color", PAPER)
	_focus_toggle.add_theme_font_size_override("font_size", 14)
	_focus_toggle.set_pressed_no_signal(_settings["speaker_focus"])
	_focus_toggle.toggled.connect(_set_speaker_focus)
	column.add_child(_focus_toggle)
	_motion_toggle = CheckButton.new()
	_motion_toggle.text = "Reduce motion (no transitions, shake or flash)"
	_motion_toggle.focus_mode = Control.FOCUS_ALL
	_motion_toggle.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	for role: String in ["font_color", "font_pressed_color", "font_hover_color", "font_hover_pressed_color", "font_focus_color"]:
		_motion_toggle.add_theme_color_override(role, PAPER)
	_motion_toggle.add_theme_font_size_override("font_size", 14)
	_motion_toggle.set_pressed_no_signal(_settings["reduced_motion"])
	_motion_toggle.toggled.connect(_set_reduced_motion)
	column.add_child(_motion_toggle)


func _volume_row(parent: Container, title: String, value: int, apply: Callable) -> HSlider:
	parent.add_child(_panel_label(title))
	var slider := HSlider.new()
	slider.min_value = 0
	slider.max_value = 100
	slider.step = 10
	slider.value = value
	slider.custom_minimum_size = Vector2(200, 24)
	slider.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	slider.focus_mode = Control.FOCUS_ALL
	slider.tooltip_text = title
	slider.value_changed.connect(apply)
	parent.add_child(slider)
	return slider


func _setting_row(parent: Container, title: String, values: Array, current: String, apply: Callable) -> Dictionary:
	parent.add_child(_panel_label(title))
	var row := HFlowContainer.new()
	row.add_theme_constant_override("h_separation", 6)
	row.add_theme_constant_override("v_separation", 6)
	parent.add_child(row)
	var group := ButtonGroup.new()
	var buttons := {}
	for value: String in values:
		var button := _small_toggle(value.capitalize())
		button.button_group = group
		button.set_pressed_no_signal(value == current)
		button.pressed.connect(apply.bind(value))
		row.add_child(button)
		_menu_buttons.append(button)
		buttons[value] = button
	return buttons


func _open_menu() -> void:
	if _panel_open():
		return
	_pause_controls(_menu_disabled)
	# The menu's own controls stay usable while it is open.
	for button: Button in _menu_buttons:
		button.disabled = _menu_disabled.get(button, false)
		_menu_disabled.erase(button)
	# From the title screen, settings only: no story is in progress to save or restart.
	for button: Button in _story_menu_buttons:
		button.disabled = _story_menu_buttons[button] or _title_showing()
	_menu_panel.show()
	_menu_close.grab_focus()
	_overlay_changed()
	_publish_qa.call_deferred()


func _close_menu() -> void:
	if not _menu_panel.visible:
		return
	_menu_panel.hide()
	_resume_controls(_menu_disabled)
	_refocus()
	_overlay_changed()
	_publish_qa.call_deferred()


func _overlay_open() -> bool:
	return _panel_open() or _title_showing()


func _panel_open() -> bool:
	return _gallery_panel.visible or _terms_open() or _log_panel.visible or _menu_panel.visible \
		or (_sound_gate != null and _sound_gate.visible)


func _overlay_changed() -> void:
	pass  # Playtests tell their page, so Escape closes the overlay before the playtest.


func _pause_controls(store: Dictionary) -> void:
	# Disable underlying focus targets as well as guarding queued action signals.
	for control: Node in _menu.get_children() + _menu_buttons + _buttons + _title_buttons.values():
		if control is Button:
			store[control] = control.disabled
			control.disabled = true


func _resume_controls(store: Dictionary) -> void:
	for control: Button in store:
		if is_instance_valid(control):
			control.disabled = store[control]
	store.clear()


func _refocus() -> void:
	if _title_showing():
		_title_buttons["Start"].grab_focus()
	elif _name_field != null:
		_name_field.grab_focus()
	elif not _buttons.is_empty():
		_buttons[0].grab_focus()


func _revealing() -> bool:
	return _reveal_elapsed < _reveal_total


func _finish_reveal() -> void:
	_reveal_total = 0.0
	_reveal_elapsed = 0.0
	_text.visible_ratio = 1.0


func _request_advance() -> void:
	# One press finishes what is still happening; the next one moves on.
	if _transitioning():
		_finish_transition()
		_publish_qa.call_deferred()
		return
	if _revealing():
		_finish_reveal()
		_publish_qa.call_deferred()
		return
	_action("advance", _player.generation, _player)


func _set_auto(on: bool) -> void:
	_auto = on
	_auto_button.set_pressed_no_signal(on)
	if on:
		_set_skip(false)
		_wait = Reading.auto_seconds(_player.view["text"], _settings["auto_speed"])
	_publish_qa.call_deferred()


func _set_skip(on: bool) -> void:
	_skip = on
	_skip_button.set_pressed_no_signal(on)
	if on:
		_set_auto(false)
		_finish_transition()
		_wait = 0.0
	_publish_qa.call_deferred()


func _set_ui_hidden(hidden: bool) -> void:
	_ui_hidden = hidden
	for control: Control in [_box, _choices, _menu, _notice]:
		control.visible = not hidden
	if not hidden:
		_refocus()
	_publish_qa.call_deferred()


func _set_text_speed(value: String) -> void:
	if not value in Reading.TEXT_SPEEDS:
		return
	_settings["text_speed"] = value
	_speed_buttons[value].set_pressed_no_signal(true)
	if value == "instant":
		_finish_reveal()
	_persist_settings()
	_publish_qa.call_deferred()


func _set_auto_speed(value: String) -> void:
	if not value in Reading.AUTO_SPEEDS:
		return
	_settings["auto_speed"] = value
	_auto_speed_buttons[value].set_pressed_no_signal(true)
	_persist_settings()
	_publish_qa.call_deferred()


func _set_speaker_focus(on: bool) -> void:
	_settings["speaker_focus"] = on
	_focus_toggle.set_pressed_no_signal(on)
	_apply_speaker_focus()
	_persist_settings()
	_publish_qa.call_deferred()


func _apply_speaker_focus() -> void:
	var speaker: Variant = _player.view["speaker"]
	var dim: bool = _settings["speaker_focus"] and speaker != null and _sprites.has(speaker) and _sprites.size() > 1
	for id: String in _sprites:
		_sprites[id].modulate = DIMMED if dim and id != speaker else Color.WHITE


func _read_settings() -> Dictionary:
	return SaveStore.read_settings()


func _persist_settings() -> void:
	if SaveStore.write_settings(_settings) != "":
		_notice.text = "Settings kept for this session. This device could not store them."


func _read_marks() -> Dictionary:
	return SaveStore.read_marks(_source["id"])


func _persist_marks() -> void:
	SaveStore.write_read_marks(_source["id"], _read.keys())


func _flush_read_marks(delta: float) -> void:
	_read_flush += delta
	if _read_dirty and _read_flush >= Reading.FLUSH_SECONDS:
		_read_dirty = false
		_read_flush = 0.0
		_persist_marks()


func _exit_tree() -> void:
	if _read_dirty:
		_read_dirty = false
		_persist_marks()


func _process(delta: float) -> void:
	if _player == null:
		return
	_flush_read_marks(delta)
	_music.tick(delta)
	_ambience.tick(delta)
	if _overlay_open() or _ui_hidden:
		return
	_tick_effect(delta)
	if _transitioning():
		_tick_transition(delta)
		return
	if _revealing():
		if _skip:
			_finish_reveal()
		else:
			_reveal_elapsed += delta
			if _revealing():
				_text.visible_ratio = _reveal_elapsed / _reveal_total
			else:
				_finish_reveal()
		return
	if _skip:
		_tick_skip(delta)
	elif _auto:
		_tick_auto(delta)


func _tick_skip(delta: float) -> void:
	var current: Dictionary = _player.view
	var read: bool = current["type"] == "line" and _read.has(Reading.read_mark(_player.state["node_id"], current["text"]))
	if not read:
		_set_skip(false)
		_notice.text = "Skip stopped: this line is new." if current["type"] == "line" else "Skip stopped."
		_start_voice.call_deferred(_voice_generation, _voice_session)
		return
	_wait -= delta
	if _wait <= 0.0:
		_wait = Reading.SKIP_SECONDS
		_action("advance", _player.generation, _player)


func _tick_auto(delta: float) -> void:
	if _player.view["type"] != "line":
		return  # Choices and endings always wait for the player.
	if _voice_player.playing:
		_wait = Reading.AFTER_VOICE_SECONDS
		return
	_wait -= delta
	if _wait <= 0.0:
		_action("advance", _player.generation, _player)


func _begin_screen(current: Dictionary) -> void:
	_wait = Reading.SKIP_SECONDS if _skip else Reading.auto_seconds(current["text"], _settings["auto_speed"])
	_reveal_elapsed = 0.0
	_reveal_total = 0.0 if _skip else Reading.reveal_seconds(current["text"], _settings["text_speed"])
	_text.visible_ratio = 0.0 if _reveal_total > 0.0 else 1.0
	if current["type"] in ["line", "choice", "end", "name"] and current["text"] != "":
		_note_backlog(current["speaker_name"], current["text"], current["speaker_color"])


func _cover(color: Color) -> ColorRect:
	var cover := ColorRect.new()
	cover.color = color
	cover.mouse_filter = Control.MOUSE_FILTER_IGNORE
	cover.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(cover)
	return cover


func _settings_saved() -> bool:
	return SaveStore.settings_saved()


func _browser_wants_less_motion() -> bool:
	if not OS.has_feature("web"):
		return false
	var browser: Variant = JavaScriptBridge.get_interface("window")
	if browser == null:
		return false
	var query: Variant = browser.matchMedia("(prefers-reduced-motion: reduce)")
	return query != null and query.matches == true


func _transitioning() -> bool:
	return _fx_kind != ""


func _present(current: Dictionary, stage: Dictionary) -> void:
	# Called before the new stage is drawn, while the old one can still be copied.
	_play_stage_sound.call_deferred(current, _last_stage == null, _player, _player.generation)
	_finish_transition()
	_finish_effect()
	var quiet: bool = _last_stage == null or _skip or _settings["reduced_motion"]
	var wanted: Variant = current["transition"]
	var kind := ""
	if not quiet:
		if wanted == null:
			kind = "soft" if stage != _last_stage else ""
		elif wanted != "cut":
			kind = wanted
	_last_stage = stage
	var effect: Variant = null if quiet else current["effect"]
	if kind != "":
		_pending_effect = effect
		_start_transition(kind)
	elif effect != null:
		_start_effect(effect)


func _start_transition(kind: String) -> void:
	_leaving = Control.new()
	_leaving.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_leaving.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_stage_root.add_child(_leaving)
	for layer: Control in [_background, _figures, _cg]:
		_leaving.add_child(layer.duplicate())
	_fx_kind = kind
	_fx_elapsed = 0.0
	_fx_total = Reading.TRANSITION_SECONDS[kind]
	if kind in ["fade", "slide"]:
		_box.modulate.a = 0.0
		_choices.modulate.a = 0.0


func _tick_transition(delta: float) -> void:
	_fx_elapsed += delta
	var progress := clampf(_fx_elapsed / _fx_total, 0.0, 1.0)
	if _fx_kind == "fade":
		if progress < 0.5:
			_curtain.color.a = progress * 2.0
		else:
			_leaving.hide()
			_curtain.color.a = 2.0 - progress * 2.0
	elif _fx_kind == "slide":
		_leaving.position.x = -size.x * progress * progress * (3.0 - 2.0 * progress)
	else:
		_leaving.modulate.a = 1.0 - progress
	if progress >= 1.0:
		_finish_transition()


func _finish_transition() -> void:
	if not _transitioning():
		return
	_stage_root.remove_child(_leaving)
	_leaving.queue_free()
	_leaving = null
	_fx_kind = ""
	_curtain.color.a = 0.0
	_box.modulate.a = 1.0
	_choices.modulate.a = 1.0
	var effect: Variant = _pending_effect
	_pending_effect = null
	if effect != null:
		_start_effect(effect)


func _start_effect(kind: String) -> void:
	_effect_kind = kind
	_effect_elapsed = 0.0


func _tick_effect(delta: float) -> void:
	if _effect_kind == "":
		return
	_effect_elapsed += delta
	var progress: float = _effect_elapsed / Reading.EFFECT_SECONDS[_effect_kind]
	if progress >= 1.0:
		_finish_effect()
	elif _effect_kind == "shake":
		var reach: float = Reading.SHAKE_PIXELS * (1.0 - progress)
		_stage_root.position = Vector2(sin(_effect_elapsed * 70.0) * reach, cos(_effect_elapsed * 53.0) * reach * 0.6)
	else:
		_flash.color.a = Reading.FLASH_ALPHA * (1.0 - progress)


func _finish_effect() -> void:
	_effect_kind = ""
	_stage_root.position = Vector2.ZERO
	_flash.color.a = 0.0


func _set_reduced_motion(on: bool) -> void:
	_settings["reduced_motion"] = on
	_motion_toggle.set_pressed_no_signal(on)
	if on:
		_finish_transition()
		_finish_effect()
	_persist_settings()
	_publish_qa.call_deferred()


func _set_channel_volume(value: float, key: String) -> void:
	_settings[key] = clampi(int(round(value)), 0, 100)
	_apply_volume()
	_persist_settings()
	_publish_qa.call_deferred()


func _set_muted(on: bool) -> void:
	_settings["muted"] = on
	_mute_toggle.set_pressed_no_signal(on)
	_apply_volume()
	_persist_settings()
	_publish_qa.call_deferred()


func _sound_allowed() -> bool:
	return not (_sound_gate != null and _sound_gate.visible) and not (_terms_open() and _terms_required)


func _track(id: Variant) -> AudioStream:
	if id == null or not _assets.has(id):
		return null
	if not _tracks.has(id):
		var stream := AudioStreamOggVorbis.load_from_buffer(_assets[id])
		if stream == null:
			return null
		stream.loop = true
		_tracks[id] = stream
	return _tracks[id]


func _play_stage_sound(current: Dictionary, instantly: bool, session: RefCounted, generation: int) -> void:
	# Deferred like the voice clip, because the start screen is built after the first render.
	if not _sound_allowed() or session != _player or generation != _player.generation:
		return
	var stage: Dictionary = current["stage"]
	var at_once: bool = instantly or _skip
	_music.change(stage.get("music"), _track(stage.get("music")), at_once)
	_ambience.change(stage.get("ambience"), _track(stage.get("ambience")), at_once)
	var kept := {}
	for id: Variant in [_music.current, _ambience.current]:
		if id != null and _tracks.has(id):
			kept[id] = _tracks[id]
	_tracks = kept  # Only what is playing stays decoded.
	var sound: Variant = current["sound"]
	if sound != null and not _skip and _assets.has(sound):
		var clip := wav_stream(_assets[sound])
		if clip != null:
			_effects_player.stream = clip
			_effects_player.play()


func _resume_stage_sound() -> void:
	# The input that opened the start screen or license also lets the page play sound.
	if _title_showing():
		_play_title_music()
		return
	_play_stage_sound(_player.view, true, _player, _player.generation)


func _has_sound() -> bool:
	if _has_voice_clips() or _theme["title"]["music"] != null:
		return true
	for node: Dictionary in _source["nodes"].values():
		if node.get("music") != null or node.get("ambience") != null or node.get("sound") != null:
			return true
	return false


func _build_terms() -> void:
	_terms_panel = PanelContainer.new()
	_terms_panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_terms_panel.mouse_filter = Control.MOUSE_FILTER_STOP
	_terms_panel.add_theme_stylebox_override("panel", _style(INK, LAMP, 0))
	_terms_panel.hide()
	add_child(_terms_panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 12)
	_terms_panel.add_child(column)
	var title := Label.new()
	title.text = "License terms for this game"
	title.add_theme_font_override("font", _font)
	title.add_theme_font_size_override("font_size", 24)
	title.add_theme_color_override("font_color", PAPER)
	column.add_child(title)
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	column.add_child(scroll)
	var text := Label.new()
	text.text = _terms
	text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	text.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	text.add_theme_font_size_override("font_size", 15)
	text.add_theme_color_override("font_color", PAPER)
	scroll.add_child(text)
	_terms_button = _small_button("I agree")
	_terms_button.size_flags_horizontal = Control.SIZE_SHRINK_END
	_terms_button.pressed.connect(_close_terms)
	column.add_child(_terms_button)


func _terms_open() -> bool:
	return _terms_panel != null and _terms_panel.visible


func _open_terms(required: bool) -> void:
	if _terms_panel == null or _terms_panel.visible:
		return
	_terms_required = required
	_terms_button.text = "I agree" if required else "Close license"
	_pause_controls(_terms_disabled)
	_terms_panel.show()
	_terms_button.grab_focus()
	_publish_qa.call_deferred()


func _close_terms() -> void:
	if not _terms_open():
		return
	var accepted := _terms_required
	if accepted:
		_persist_terms()
	_terms_required = false
	_terms_panel.hide()
	_resume_controls(_terms_disabled)
	_refocus()
	if accepted:
		# The agreeing click also lets the browser play sound: start the first line's clip.
		_start_voice.call_deferred(_voice_generation, _voice_session)
		_resume_stage_sound.call_deferred()
	_publish_qa.call_deferred()


func _digest(text: String) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(text.to_utf8_buffer())
	return context.finish().hex_encode()


func _read_terms() -> String:
	return SaveStore.read_terms(_source["id"])


func _persist_terms() -> void:
	if SaveStore.write_terms(_source["id"], _digest(_terms)) != "":
		_notice.text = "License accepted for this session. This device could not keep it."


func _build_gallery() -> void:
	_gallery_panel = PanelContainer.new()
	_gallery_panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_gallery_panel.add_theme_stylebox_override("panel", _style(INK, LAMP, 0))
	_gallery_panel.hide()
	add_child(_gallery_panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 12)
	_gallery_panel.add_child(column)
	var close := _small_button("Close gallery")
	close.pressed.connect(_close_gallery)
	column.add_child(close)
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	column.add_child(scroll)
	_gallery_entries = VBoxContainer.new()
	_gallery_entries.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(_gallery_entries)
	_gallery_image = TextureRect.new()
	_gallery_image.custom_minimum_size.y = 180
	_gallery_image.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_gallery_image.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_gallery_image.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	column.add_child(_gallery_image)


func _open_gallery() -> void:
	if _gallery_panel.visible:
		return
	_pause_controls(_gallery_disabled)
	for child in _gallery_entries.get_children():
		_gallery_entries.remove_child(child)
		child.queue_free()
	var entries: Array = _player.gallery
	if entries.is_empty():
		var empty := Label.new()
		empty.text = "This story has no CGs."
		_gallery_entries.add_child(empty)
	for index in range(entries.size()):
		var entry: Dictionary = entries[index]
		var button := _small_button("CG %d" % (index + 1) + ("" if entry["unlocked"] else " · Locked"))
		button.disabled = not entry["unlocked"]
		button.pressed.connect(_show_gallery_image.bind(entry["id"]))
		_gallery_entries.add_child(button)
	_gallery_panel.show()
	_gallery_panel.get_child(0).get_child(0).grab_focus()
	_overlay_changed()
	_publish_qa.call_deferred()


func _show_gallery_image(id: String) -> void:
	# Recheck even if an old queued button signal is delivered later.
	if _gallery_panel.visible and id in _player.seen_cgs:
		var image := Image.new()
		if image.load_png_from_buffer(_assets[id]) == OK:
			_gallery_image.texture = ImageTexture.create_from_image(image)
	_publish_qa.call_deferred()


func _close_gallery() -> void:
	if not _gallery_panel.visible:
		return
	_gallery_panel.hide()
	_gallery_image.texture = null
	_resume_controls(_gallery_disabled)
	_refocus()
	_overlay_changed()
	_publish_qa.call_deferred()


func _gallery_path() -> String:
	return SaveStore.gallery_path(_source["id"])


func _read_gallery() -> Array:
	return SaveStore.read_gallery(_source["id"])


func _persist_gallery() -> void:
	var seen: Array = _player.seen_cgs
	if seen != _gallery_saved:
		if SaveStore.write_gallery(_source["id"], seen) == "":
			_gallery_saved = seen
		else:
			_notice.text = "CGs unlocked for this session. This device could not keep the gallery."


func _set_volume(value: float) -> void:
	_voice_volume = clampi(int(round(value)), 0, 100)
	_settings["voice_volume"] = _voice_volume
	_apply_volume()
	_persist_settings()
	_publish_qa.call_deferred()


func _apply_volume() -> void:
	var loudness := 0.0 if _settings["muted"] else 1.0
	_voice_player.volume_db = SoundChannel.decibels(loudness * _voice_volume / 100.0)
	_effects_player.volume_db = SoundChannel.decibels(loudness * _settings["effects_volume"] / 100.0)
	_music.set_volume(loudness * _settings["music_volume"] / 100.0)
	_ambience.set_volume(loudness * _settings["ambience_volume"] / 100.0)


static func wav_stream(data: PackedByteArray) -> AudioStreamWAV:
	# The canonical form only (ADR 0043): RIFF/WAVE, a 16-byte PCM fmt chunk, 1-2
	# channels, a common rate, 16 bits, then one data chunk that ends the file.
	if data.size() < 46 or data.size() > 10485760:
		return null
	if data.slice(0, 4).get_string_from_ascii() != "RIFF" or data.decode_u32(4) != data.size() - 8:
		return null
	if data.slice(8, 16).get_string_from_ascii() != "WAVEfmt " or data.decode_u32(16) != 16:
		return null
	var channels := data.decode_u16(22)
	var rate := data.decode_u32(24)
	if data.decode_u16(20) != 1 or not channels in [1, 2] or not rate in [16000, 22050, 24000, 32000, 44100, 48000]:
		return null
	if data.decode_u16(34) != 16 or data.decode_u16(32) != channels * 2 or data.decode_u32(28) != rate * channels * 2:
		return null
	var size := data.decode_u32(40)
	if data.slice(36, 40).get_string_from_ascii() != "data" or size != data.size() - 44 or size == 0:
		return null
	if size % (channels * 2) != 0 or size / (channels * 2) > rate * 60:
		return null
	var stream := AudioStreamWAV.new()
	stream.format = AudioStreamWAV.FORMAT_16_BITS
	stream.mix_rate = rate
	stream.stereo = channels == 2
	stream.data = data.slice(44)
	return stream


func _voice_stream(id: String) -> AudioStreamWAV:
	if not _voice_streams.has(id):
		_voice_streams[id] = wav_stream(_assets[id]) if _assets.has(id) else null
	return _voice_streams[id]


func _play_voice(current: Dictionary) -> void:
	# A new screen stops the previous clip; a settled voiced line plays its own once.
	if _player.generation == _voice_generation and _player == _voice_session:
		return
	_voice_generation = _player.generation
	_voice_session = _player
	_voice_player.stop()
	_voice_player.stream = null
	var id: Variant = current.get("voice")
	if id is String:
		var stream := _voice_stream(id)
		if stream != null:
			_voice_player.stream = stream
			_apply_volume()
			# Started on the next frame: the first line settles while the stage is built.
			_start_voice.call_deferred(_voice_generation, _voice_session)


func _start_voice(generation: int, session: RefCounted) -> void:
	if _sound_gate != null and _sound_gate.visible:
		return  # Played once the start screen is opened.
	if _terms_open() and _terms_required:
		return  # Played once the player accepts the license terms.
	if _skip:
		return  # Lines flying past stay silent; the line Skip stops on plays.
	if generation == _voice_generation and session == _voice_session and _voice_player.stream != null:
		_voice_player.play()


func _has_voice_clips() -> bool:
	for node: Dictionary in _source["nodes"].values():
		var voice: Variant = node.get("voice")
		if voice is Dictionary and voice.has("audio"):
			return true
	return false


func _sound_blocked() -> bool:
	# A fresh AudioContext starts suspended where the page may not play sound yet.
	# No eval: Studio playtests forbid it.
	if not OS.has_feature("web") or JavaScriptBridge.get_interface("AudioContext") == null:
		return false
	var probe: JavaScriptObject = JavaScriptBridge.create_object("AudioContext")
	var state: Variant = probe.state
	probe.close()
	return state != "running"


func _gate_sound() -> void:
	if _terms_open() and _terms_required:
		return  # Agreeing to the terms is the input that lets the page play sound.
	if _sound_gate == null and _sound_blocked():
		_build_sound_gate()
		_publish_qa.call_deferred()


func _build_sound_gate() -> void:
	_sound_gate = PanelContainer.new()
	_sound_gate.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_sound_gate.mouse_filter = Control.MOUSE_FILTER_STOP
	_sound_gate.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	_sound_gate.add_theme_stylebox_override("panel", _style(Color(INK, 0.82), Color.TRANSPARENT, 0, 0))
	var label := Label.new()
	label.text = "Click or press any key to start\n" + ("This story has voice acting." if _has_voice_clips() else "This story has sound.")
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_override("font", _font)
	label.add_theme_font_size_override("font_size", 26)
	label.add_theme_color_override("font_color", PAPER)
	_sound_gate.add_child(label)
	add_child(_sound_gate)


func _open_sound_gate() -> void:
	# The engine resumes browser audio on this same input; start the settled line's clip.
	_sound_gate.hide()
	if not _title_showing():
		_start_voice.call_deferred(_voice_generation, _voice_session)
	_resume_stage_sound.call_deferred()
	_publish_qa.call_deferred()


func current_voice() -> Variant:
	var id: Variant = _player.view.get("voice")
	if id is String and _voice_player.stream != null and _voice_player.stream == _voice_streams.get(id):
		return id
	return null


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
	if _player.generation != _screen_generation or _player != _screen_session:
		_present(current, stage)
	_play_voice(current)
	var in_use := {}
	_cg.texture = _texture(stage["cg"])
	if stage["cg"] != null:
		in_use[stage["cg"]] = true
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
		_sprites[id].set_meta("x", item.get("x"))
		shown[id] = true
	for id: String in _sprites.keys():
		if not shown.has(id):
			_sprites[id].queue_free()
			_sprites.erase(id)
	_apply_speaker_focus()
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
	if _player.generation != _screen_generation or _player != _screen_session:
		_screen_generation = _player.generation
		_screen_session = _player
		_begin_screen(current)
	_continue.visible = current["type"] == "line"
	for child in _choices.get_children():
		_choices.remove_child(child)
		child.queue_free()
	_buttons.clear()
	_name_field = null
	var generation: int = _player.generation
	if current["type"] == "line":
		_buttons.append(_continue)
	elif current["type"] == "choice":
		for index in range(current["options"].size()):
			var option: Dictionary = current["options"][index]
			_add_choice(option["text"], "choose:" + option["id"], generation)
	elif current["type"] == "name":
		_add_name_field(current["player_name"], generation)
	elif current["type"] in ["end", "fault"]:
		var again := _choice_button("Play again")
		again.pressed.connect(_toolbar.bind("Restart"))
		_choices.add_child(again)
		_buttons.append(again)
	_layout()
	if _name_field != null:
		_name_field.call_deferred("grab_focus")
	elif not _buttons.is_empty():
		_buttons[0].call_deferred("grab_focus")
	_publish_qa.call_deferred()
	_persist_gallery()


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


func _add_name_field(current: String, generation: int) -> void:
	var palette: Dictionary = _theme["choices"]
	_name_field = LineEdit.new()
	_name_field.text = current
	_name_field.select_all_on_focus = true
	_name_field.max_length = PlayerScript.NAME_LIMIT
	_name_field.custom_minimum_size.y = 52
	_name_field.placeholder_text = "Your name"
	_name_field.alignment = HORIZONTAL_ALIGNMENT_CENTER
	_name_field.add_theme_font_override("font", _font)
	_name_field.add_theme_color_override("font_color", _color(palette["text"]))
	_name_field.add_theme_color_override("caret_color", _color(palette["text"]))
	var box := _style(_color(palette["background"]), _color(palette["border"]), _theme["textbox"]["radius"])
	_name_field.add_theme_stylebox_override("normal", box)
	var focused := box.duplicate()
	focused.set_border_width_all(4)
	_name_field.add_theme_stylebox_override("focus", focused)
	_name_field.text_submitted.connect(_submit_name.bind(generation, _player))
	_choices.add_child(_name_field)
	var confirm := _choice_button("That's me")
	confirm.pressed.connect(_confirm_name.bind(generation, _player))
	_choices.add_child(confirm)
	_buttons.append(confirm)


func _confirm_name(generation: int, session: RefCounted) -> void:
	if _name_field != null:
		_submit_name(_name_field.text, generation, session)


func _submit_name(typed: String, generation: int, session: RefCounted) -> void:
	if not _can_show(PlayerScript.clean_name(typed, "")):
		# It would be empty boxes in every line that says it, so ask rather than save that.
		_notice.text = "This game's font can't show some of those letters. Please try others."
		_publish_qa.call_deferred()
		return
	_action("name:" + typed, generation, session)


func _can_show(typed: String) -> bool:
	if _font_falls_back():
		return true
	for index in range(typed.length()):
		var code := typed.unicode_at(index)
		if code != 0x200C and code != 0x200D and not _font.has_char(code):
			return false
	return true


func _font_falls_back() -> bool:
	return not OS.has_feature("web")  # A desktop has system fonts to borrow; a browser gives none.


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
	if _title_panel != null:
		_title_heading.add_theme_font_size_override("font_size", int(round(56 * scale_factor)))
		_title_status.add_theme_font_size_override("font_size", int(round(16 * scale_factor)))
		for button: Button in _title_buttons.values():
			button.add_theme_font_size_override("font_size", int(round(20 * scale_factor)))
			button.custom_minimum_size.x = minf(size.x - 48.0, 360.0 * scale_factor)
	var font_size := int(round(int(_theme["font"]["size"]) * scale_factor))
	_text.add_theme_font_size_override("normal_font_size", font_size)
	_name.add_theme_font_size_override("font_size", maxi(12, int(font_size * 0.8)))
	if _name_field != null:
		_name_field.add_theme_font_size_override("font_size", font_size)
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
	# Characters keep their aspect. Without framing they stand on the bottom edge and fill
	# most of the height within their slot; a character's framing (runtime 0.4.0) sets the
	# drawn height and the top edge instead, so tall figures are cut off below the screen.
	var slot_width := size.x * 0.36
	var slot_height := size.y * 0.92
	for id: String in _sprites:
		var figure: TextureRect = _sprites[id]
		var texture := figure.texture
		if texture == null:
			figure.size = Vector2.ZERO
			continue
		var natural := Vector2(texture.get_width(), texture.get_height())
		var framing: Dictionary = _source["characters"][id].get("stage", {})
		var drawn: Vector2
		var top: float
		if framing.is_empty():
			drawn = natural * minf(slot_width / natural.x, slot_height / natural.y)
			top = size.y - drawn.y
		else:
			var scale_percent: int = framing.get("scale", 92)
			drawn = natural * (size.y * scale_percent / 100.0 / natural.y)
			top = size.y * framing.get("top", maxi(0, 100 - scale_percent)) / 100.0
		var place: Variant = figure.get_meta("x") if figure.has_meta("x") else null  # set_meta(null) removes the key.
		var center: float = (place / 100.0 if place != null else SLOTS[figure.get_meta("position")]) * size.x
		figure.position = Vector2(center - drawn.x / 2.0, top)
		figure.size = drawn
	_publish_qa.call_deferred()


func _action(action: String, generation: int, session: RefCounted) -> void:
	if _overlay_open() or _ui_hidden or session != _player:
		return
	var left: Dictionary = _player.view
	var node_id: String = _player.state["node_id"]
	if _player.act(action, generation) != "":
		return
	if left["type"] == "line" and _read.size() < Reading.MAX_READ_MARKS:
		_read[Reading.read_mark(node_id, left["text"])] = true
		_read_dirty = true
	elif left["type"] == "choice":
		for option: Dictionary in left["options"]:
			if action == "choose:" + option["id"]:
				_note_backlog(null, "› " + option["text"])
	elif left["type"] == "name":
		_note_backlog(null, "› " + _player.state["player_name"])
	_notice.text = ""
	_render()


func _save_path() -> String:
	return SaveStore.path_for(_hash)


func _toolbar(action: String) -> void:
	if _gallery_panel.visible or _terms_open() or _log_panel.visible:
		return
	# Everything in the menu closes it first: results show on the stage behind it.
	_close_menu()
	if action == "Menu":
		_open_menu()
	elif action == "Log":
		_open_log()
	elif action == "Auto":
		_set_auto(not _auto)
		_refocus()
	elif action == "Skip":
		_set_skip(not _skip)
		_refocus()
	elif action == "Hide":
		_set_ui_hidden(true)
	elif action == "License":
		_open_terms(false)
	elif action == "Gallery":
		_open_gallery()
	elif action == "Title screen":
		_show_title()
	elif action == "Restart":
		_close_gallery()
		_set_auto(false)
		_set_skip(false)
		_backlog.clear()
		_last_stage = null  # A new start is a cut, whatever the first scene asks for.
		_player = PlayerScript.new(_source, _hash, _player.seen_cgs)
		_notice.text = "Started over. Your saved game is still available."
		_render()
	elif action == "Save":
		var error: String = SaveStore.write_save(_hash, _player.save())
		_notice.text = "Saved on this device." if error == "" else "This device could not save your progress. Your previous save is unchanged."
		if error == "" and OS.has_feature("web") and not OS.is_userfs_persistent():
			_notice.text = "Saved for this session. Browser storage is unavailable."
		_publish_qa.call_deferred()
	elif action == "Quick save":
		var error: String = SaveStore.write_quick_save(_hash, _player.save())
		_notice.text = "Quick saved." if error == "" else "This device could not save your progress. Your previous quick save is unchanged."
		if error == "" and OS.has_feature("web") and not OS.is_userfs_persistent():
			_notice.text = "Quick saved for this session. Browser storage is unavailable."
		_publish_qa.call_deferred()
	elif action == "Load":
		_load_slot(SaveStore.read_save(_hash), "No saved game on this device yet.", "Saved game loaded.")
	elif action == "Quick load":
		_load_slot(SaveStore.read_quick_save(_hash), "No quick save on this device yet.", "Quick save loaded.")


func _load_slot(saved: Dictionary, missing: String, loaded: String) -> bool:
	if saved.get("error") == "not_found":
		_notice.text = missing
		_publish_qa.call_deferred()
		return false
	if saved.get("error", "save_read_failed") != "":
		_notice.text = "That saved game cannot be loaded. Your progress is unchanged."
		_publish_qa.call_deferred()
		return false
	if _player.load_save(saved["data"]) != "":
		_notice.text = "That saved game cannot be loaded. Your progress is unchanged."
		_publish_qa.call_deferred()
		return false
	_set_auto(false)
	_set_skip(false)
	_note_backlog(null, "— " + loaded.trim_suffix(".") + " —")
	_last_stage = null  # So is arriving from a save.
	_notice.text = loaded
	_render()
	return true


func _gui_input(event: InputEvent) -> void:
	# Clicking or tapping the stage advances a line, as in most visual novels. A right
	# click hides the interface and scrolling up opens the log, as they usually do too.
	if _overlay_open() or _ui_hidden:
		return
	if event is InputEventMouseButton and event.pressed:
		if event.button_index == MOUSE_BUTTON_LEFT and _player.view["type"] == "line":
			_set_skip(false)
			_request_advance()
			accept_event()
		elif event.button_index == MOUSE_BUTTON_RIGHT:
			_set_ui_hidden(true)
			accept_event()
		elif event.button_index == MOUSE_BUTTON_WHEEL_UP:
			_open_log()
			accept_event()


func _input(event: InputEvent) -> void:
	if _sound_gate != null and _sound_gate.visible:
		# The first click, tap or key press opens the story; it never advances it.
		var key: bool = event is InputEventKey and event.pressed and not event.echo
		if key or ((event is InputEventMouseButton or event is InputEventScreenTouch) and event.pressed):
			if key and event.keycode in [KEY_ENTER, KEY_SPACE]:
				_advance_key = event.keycode  # Its release must not press Continue either.
			_open_sound_gate()
		if not event is InputEventMouseMotion:
			get_viewport().set_input_as_handled()
		return
	if _ui_hidden:
		# Any press brings the interface back; it never advances the story as well.
		var pressed_key: bool = event is InputEventKey and event.pressed and not event.echo
		if pressed_key or ((event is InputEventMouseButton or event is InputEventScreenTouch) and event.pressed):
			if pressed_key and event.keycode in [KEY_ENTER, KEY_SPACE]:
				_advance_key = event.keycode
			_set_ui_hidden(false)
		if not event is InputEventMouseMotion:
			get_viewport().set_input_as_handled()
		return
	if not event is InputEventKey or not event.keycode in [KEY_ENTER, KEY_SPACE] or _terms_open():
		return
	# Claim the entire keystroke before GUI dispatch: the focused Continue button
	# otherwise activates on release after key-down already settled the next line.
	if _advance_key == event.keycode:
		if not event.pressed:
			_advance_key = 0
		get_viewport().set_input_as_handled()
		return
	if _player == null or _overlay_open() or not event.pressed or event.echo or event.ctrl_pressed or event.meta_pressed or event.alt_pressed:
		return
	var focused := get_viewport().gui_get_focus_owner()
	if _player.view["type"] == "line" and (focused == null or focused == _continue):
		_advance_key = event.keycode
		_set_skip(false)
		_request_advance()
		get_viewport().set_input_as_handled()


func _unhandled_key_input(event: InputEvent) -> void:
	if not event is InputEventKey or not event.pressed or event.echo or event.ctrl_pressed or event.meta_pressed or event.alt_pressed:
		return
	if _terms_open():
		if event.keycode == KEY_ESCAPE and not _terms_required:
			_close_terms()
		get_viewport().set_input_as_handled()
		return
	if _gallery_panel.visible:
		if event.keycode == KEY_ESCAPE:
			_close_gallery()
		get_viewport().set_input_as_handled()
		return
	if _log_panel.visible:
		if event.keycode in [KEY_ESCAPE, KEY_L]:
			_close_log()
		elif event.keycode in [KEY_UP, KEY_DOWN, KEY_PAGEUP, KEY_PAGEDOWN]:
			var step: int = {KEY_UP: -40, KEY_DOWN: 40, KEY_PAGEUP: -300, KEY_PAGEDOWN: 300}[event.keycode]
			_log_scroll.scroll_vertical += step
		get_viewport().set_input_as_handled()
		return
	if _menu_panel.visible:
		if event.keycode == KEY_ESCAPE:
			_close_menu()
		get_viewport().set_input_as_handled()
		return
	if event.keycode == KEY_M:
		_set_muted(not _settings["muted"])
		get_viewport().set_input_as_handled()
		return
	if _title_showing():
		get_viewport().set_input_as_handled()  # No story is on screen for a shortcut to act on.
		return
	var shortcut: String = {KEY_L: "Log", KEY_A: "Auto", KEY_S: "Skip", KEY_H: "Hide", KEY_ESCAPE: "Menu"}.get(event.keycode, "")
	if not OS.has_feature("web"):
		# A browser takes F5 for itself, so web players use the menu.
		shortcut = {KEY_F5: "Quick save", KEY_F9: "Quick load"}.get(event.keycode, shortcut)
	if shortcut != "":
		_toolbar(shortcut)
		get_viewport().set_input_as_handled()
		return
	var current: Dictionary = _player.view
	var action := ""
	if current["type"] == "line" and event.keycode in [KEY_ENTER, KEY_SPACE]:
		var focused := get_viewport().gui_get_focus_owner()
		if focused == null or focused == _continue:
			_request_advance()
			get_viewport().set_input_as_handled()
			return
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
	var toolbar: Array = []
	for button: Node in _menu.get_children() + _menu_buttons:
		if button is Button and button.is_visible_in_tree():
			toolbar.append(_rect(button).merged({"label": button.text, "disabled": button.disabled}))
	var gallery_controls: Array = []
	if _gallery_panel.visible:
		var close: Button = _gallery_panel.get_child(0).get_child(0)
		gallery_controls.append(_rect(close).merged({"label": close.text, "disabled": close.disabled}))
		for button: Node in _gallery_entries.get_children():
			if button is Button:
				gallery_controls.append(_rect(button).merged({"label": button.text, "disabled": button.disabled}))
	var snapshot := {"node_id": _player.state["node_id"], "status": _player.state["status"],
		"ending": _player.state["ending"], "fault": _player.state["fault"], "view": _player.view,
		"has_save": FileAccess.file_exists(_save_path()), "viewport": {"width": size.x, "height": size.y},
		"controls": controls, "notice": _notice.text, "layout": "stage",
		"textbox": _rect(_box), "name_visible": _name_box.visible, "figures": figures,
		"background_loaded": _background.texture != null, "custom_font": _font != DisplayFont,
		"cg_loaded": _cg.texture != null, "gallery": _player.gallery, "gallery_open": _gallery_panel.visible,
		"toolbar": toolbar, "gallery_controls": gallery_controls,
		"terms": _terms != null, "terms_open": _terms_open(), "terms_required": _terms_required, "gallery_image_loaded": _gallery_image.texture != null,
		"voice_volume": _voice_volume, "voice_clip": current_voice(), "voice_playing": _voice_player.playing,
		"volume_slider": _rect(_volume_slider), "sound_gate": _sound_gate != null and _sound_gate.visible,
		"text_speed": _settings["text_speed"], "auto_speed": _settings["auto_speed"], "speaker_focus": _settings["speaker_focus"],
		"auto": _auto, "skip": _skip, "ui_hidden": _ui_hidden, "revealing": _revealing(),
		"transition": _fx_kind, "effect": _effect_kind, "reduced_motion": _settings["reduced_motion"],
		"music": _music.current, "ambience": _ambience.current, "music_playing": _music.playing(), "sound_playing": _effects_player.playing, "muted": _settings["muted"],
		"player_name": _player.state.get("player_name"), "name_asked": _name_field != null,
		"title_open": _title_showing(), "title_art": _title_art != null and _title_art.texture != null,
		"log_open": _log_panel.visible, "menu_open": _menu_panel.visible, "backlog": backlog_rows().size(), "read_marks": _read.size()}
	var browser: Variant = JavaScriptBridge.get_interface("window")
	var json: Variant = JavaScriptBridge.get_interface("JSON")
	if browser != null and json != null:
		browser.__flintNarrativeQA = json.parse(JSON.stringify(snapshot))
