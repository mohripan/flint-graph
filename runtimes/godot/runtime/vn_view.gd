# SPDX-License-Identifier: MIT
# Visual novel layout for story format 2 (ADR 0040): a full-screen stage, characters in
# three slots standing on the bottom edge, and a themed text box. Story strings render
# as plain text; images and fonts come only from verified package bytes.
extends Control

const PlayerScript = preload("res://runtime/player.gd")
const SaveStore = preload("res://runtime/save_store.gd")
const PlayerTerms = preload("res://runtime/player_terms.gd")
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
# Terms a voice model license puts on players (ADR 0044): shown once before play and
# again from the menu. Until they are accepted the story does not start or speak.
var _terms: Variant = null
var _terms_panel: PanelContainer
var _terms_button: Button
var _terms_required := false
var _terms_disabled: Dictionary = {}


func configure(source: Dictionary, package_hash: String, assets: Dictionary, notices: String = "") -> void:
	_terms = PlayerTerms.parse(notices).get("terms")
	_source = source
	_hash = package_hash
	_assets = assets.duplicate()
	_theme = _merged(source.get("theme", {}))
	_font = _story_font()
	_gallery_saved = _read_gallery()
	_voice_volume = _read_volume()
	_player = PlayerScript.new(source, package_hash, _gallery_saved)
	_build()
	if _terms != null:
		_build_terms()
		if _read_terms() != _digest(_terms):
			_open_terms(true)
	if _has_voice_clips():
		# Deferred: playtests configure inside the browser callback that delivers the
		# story, where the probe cannot run. It still runs before the first clip starts.
		_gate_sound.call_deferred()
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
	_figures.clip_contents = true  # Framed figures continue below the screen edge.
	_figures.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_figures.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_figures)
	_cg = TextureRect.new()
	_cg.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_cg.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	_cg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_cg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_cg)  # Over the stage; text, choices and controls are drawn above it.
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
	for item: String in ["Save", "Load", "Restart", "Gallery"] + (["License"] if _terms != null else []):
		var button := _small_button(item)
		button.pressed.connect(_toolbar.bind(item))
		_menu.add_child(button)
	var voice_label := Label.new()
	voice_label.text = "Voice"
	voice_label.add_theme_color_override("font_color", PAPER)
	voice_label.add_theme_color_override("font_outline_color", INK)
	voice_label.add_theme_constant_override("outline_size", 4)
	voice_label.add_theme_font_size_override("font_size", 14)
	_menu.add_child(voice_label)
	_volume_slider = HSlider.new()
	_volume_slider.min_value = 0
	_volume_slider.max_value = 100
	_volume_slider.step = 10
	_volume_slider.value = _voice_volume
	_volume_slider.custom_minimum_size = Vector2(96, 0)
	_volume_slider.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	_volume_slider.focus_mode = Control.FOCUS_ALL
	_volume_slider.tooltip_text = "Voice volume"
	_volume_slider.value_changed.connect(_set_volume)
	_menu.add_child(_volume_slider)
	_voice_player = AudioStreamPlayer.new()
	add_child(_voice_player)
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
	_build_gallery()


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
	for button: Node in _menu.get_children() + _buttons:
		if button is Button:
			_terms_disabled[button] = button.disabled
			button.disabled = true
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
	for button: Button in _terms_disabled:
		if is_instance_valid(button):
			button.disabled = _terms_disabled[button]
	_terms_disabled.clear()
	if not _buttons.is_empty():
		_buttons[0].grab_focus()
	if accepted:
		# The agreeing click also lets the browser play sound: start the first line's clip.
		_start_voice.call_deferred(_voice_generation, _voice_session)
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
	# Disable underlying focus targets as well as guarding queued action signals.
	for button: Node in _menu.get_children() + _buttons:
		if button is Button:
			_gallery_disabled[button] = button.disabled
			button.disabled = true
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
	_publish_qa.call_deferred()


func _show_gallery_image(id: String) -> void:
	# Recheck even if an old queued button signal is delivered later.
	if _gallery_panel.visible and id in _player.seen_cgs:
		var image := Image.new()
		if image.load_png_from_buffer(_assets[id]) == OK:
			_gallery_image.texture = ImageTexture.create_from_image(image)
	_publish_qa.call_deferred()


func _close_gallery() -> void:
	_gallery_panel.hide()
	_gallery_image.texture = null
	for button: Button in _gallery_disabled:
		if is_instance_valid(button):
			button.disabled = _gallery_disabled[button]
	_gallery_disabled.clear()
	if not _buttons.is_empty():
		_buttons[0].grab_focus()
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


func _read_volume() -> int:
	return SaveStore.read_voice_volume()


func _persist_volume() -> void:
	if SaveStore.write_voice_volume(_voice_volume) != "":
		_notice.text = "Voice volume set for this session. This device could not keep it."


func _set_volume(value: float) -> void:
	_voice_volume = clampi(int(round(value)), 0, 100)
	_apply_volume()
	_persist_volume()
	_publish_qa.call_deferred()


func _apply_volume() -> void:
	_voice_player.volume_db = linear_to_db(_voice_volume / 100.0) if _voice_volume > 0 else -80.0


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
	label.text = "Click or press any key to start\nThis story has voice acting."
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
	_start_voice.call_deferred(_voice_generation, _voice_session)
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
		var place: Variant = figure.get_meta("x", null)  # set_meta(null) removes the key.
		var center: float = (place / 100.0 if place != null else SLOTS[figure.get_meta("position")]) * size.x
		figure.position = Vector2(center - drawn.x / 2.0, top)
		figure.size = drawn
	_publish_qa.call_deferred()


func _action(action: String, generation: int, session: RefCounted) -> void:
	if not _gallery_panel.visible and not _terms_open() and session == _player and _player.act(action, generation) == "":
		_notice.text = ""
		_render()


func _save_path() -> String:
	return SaveStore.path_for(_hash)


func _toolbar(action: String) -> void:
	if _gallery_panel.visible or _terms_open():
		return
	if action == "License":
		_open_terms(false)
	elif action == "Gallery":
		_open_gallery()
	elif action == "Restart":
		_close_gallery()
		_player = PlayerScript.new(_source, _hash, _player.seen_cgs)
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
	if _gallery_panel.visible or _terms_open():
		return
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		if _player.view["type"] == "line":
			_action("advance", _player.generation, _player)
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
	if not event is InputEventKey or not event.keycode in [KEY_ENTER, KEY_SPACE] or _terms_open():
		return
	# Claim the entire keystroke before GUI dispatch: the focused Continue button
	# otherwise activates on release after key-down already settled the next line.
	if _advance_key == event.keycode:
		if not event.pressed:
			_advance_key = 0
		get_viewport().set_input_as_handled()
		return
	if _player == null or _gallery_panel.visible or not event.pressed or event.echo or event.ctrl_pressed or event.meta_pressed or event.alt_pressed:
		return
	var focused := get_viewport().gui_get_focus_owner()
	if _player.view["type"] == "line" and (focused == null or focused == _continue):
		_advance_key = event.keycode
		_action("advance", _player.generation, _player)
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
	var current: Dictionary = _player.view
	var action := ""
	if current["type"] == "line" and event.keycode in [KEY_ENTER, KEY_SPACE]:
		var focused := get_viewport().gui_get_focus_owner()
		if focused == null or focused == _continue:
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
	var toolbar: Array = []
	for button: Node in _menu.get_children():
		if button is Button:
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
		"volume_slider": _rect(_volume_slider), "sound_gate": _sound_gate != null and _sound_gate.visible}
	var browser: Variant = JavaScriptBridge.get_interface("window")
	var json: Variant = JavaScriptBridge.get_interface("JSON")
	if browser != null and json != null:
		browser.__flintNarrativeQA = json.parse(JSON.stringify(snapshot))
