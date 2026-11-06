# Trusted UI/file-boundary regression harness, never included in creator exports.
extends SceneTree

class FaultIO:
	extends RefCounted
	var mode: String
	func _init(failure: String) -> void:
		mode = failure
	func prepare(path: String) -> Error:
		return DirAccess.make_dir_recursive_absolute(path)
	func write(path: String, data: PackedByteArray) -> Error:
		var file := FileAccess.open(path, FileAccess.WRITE)
		if file == null:
			return ERR_FILE_CANT_WRITE
		file.store_buffer(data.slice(0, 1) if mode in ["write", "verify"] else data)
		file.close()
		return ERR_FILE_CANT_WRITE if mode == "write" else OK
	func read(path: String, _limit: int) -> Dictionary:
		return {"data": FileAccess.get_file_as_bytes(path), "error": ""}
	func replace(source: String, target: String) -> Error:
		return ERR_FILE_CANT_WRITE if mode == "replace" else DirAccess.rename_absolute(source, target)


func _find(node: Node, label: String) -> Button:
	if node is Button and node.text == label:
		return node
	for child in node.get_children():
		var found := _find(child, label)
		if found != null:
			return found
	return null


func _body(node: Node) -> String:
	if node is RichTextLabel:
		return node.get_parsed_text()
	for child in node.get_children():
		var found := _body(child)
		if found != "":
			return found
	return ""


func _key(code: int) -> InputEventKey:
	var event := InputEventKey.new()
	event.keycode = code
	event.pressed = true
	return event


func _initialize() -> void:
	var bootstrap: Node = load("res://runtime/bootstrap.gd").new()
	var checked: Dictionary = bootstrap.verify_content()
	bootstrap.free()
	var config: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://qualification.json"))
	if config["case"] in ["cg_keyboard", "cg_keyboard_gallery"]:
		var stage: Control = load("res://runtime/vn_view.gd").new()
		root.add_child(stage)
		stage.size = Vector2(1280, 720)
		stage.configure(checked["story"], checked["package_hash"], checked["assets"])
		stage._set_text_speed("instant")
		stage._set_reduced_motion(true)
		await process_frame
		await process_frame
		if config["case"] == "cg_keyboard_gallery":
			stage._toolbar("Menu")
			_find(stage, "Gallery").grab_focus()
		var down := InputEventKey.new()
		down.keycode = KEY_ENTER
		down.pressed = true
		Input.parse_input_event(down)
		await process_frame
		var up := InputEventKey.new()
		up.keycode = KEY_ENTER
		up.pressed = false
		Input.parse_input_event(up)
		await process_frame
		await process_frame
		print("UI_RESULT:" + JSON.stringify({"node_id": stage._player.state["node_id"], "gallery_open": stage._gallery_panel.visible}))
		quit(0)
		return
	if config["case"] == "terms_parse":
		# The shared player-terms cases (ADR 0045), parsed by the runtime's own script.
		var terms_script: GDScript = load("res://runtime/player_terms.gd")
		var parsed_terms: Array = []
		for notices: String in config["notices"]:
			parsed_terms.append(terms_script.parse(notices))
		print("UI_RESULT:" + JSON.stringify(parsed_terms))
		quit(0)
		return
	if config["case"] in ["terms", "terms_preview"]:
		# Player terms (ADR 0045): a screen before play that holds the story and its voice
		# until accepted, kept on the device (never in playtests) and rereadable.
		var view: GDScript = load("res://preview/vn_view.gd" if config["case"] == "terms_preview" else "res://runtime/vn_view.gd")
		var notices: String = FileAccess.get_file_as_string("res://content/NOTICES.txt")
		var launches: Array = []
		for text: String in [notices, notices, config["changed_notices"]]:
			var stage: Control = view.new()
			root.add_child(stage)
			stage.size = Vector2(1280, 720)
			stage.configure(checked["story"], checked["package_hash"], checked["assets"], text)
			stage._set_text_speed("instant")
			stage._set_reduced_motion(true)
			await process_frame
			await process_frame
			var first: String = stage._player.state["node_id"]
			var launch := {"open": stage._terms_open(), "required": stage._terms_required,
				"playing": stage._voice_player.playing, "license_button": _find(stage, "License") != null}
			if stage._terms_open():
				var click := InputEventMouseButton.new()
				click.button_index = MOUSE_BUTTON_LEFT
				click.position = Vector2(640, 600)
				for pressed: bool in [true, false]:
					click.pressed = pressed
					root.push_input(click.duplicate())
				stage._unhandled_key_input(_key(KEY_ENTER))
				stage._unhandled_key_input(_key(KEY_ESCAPE))
				await process_frame
				launch["still_open"] = stage._terms_open()
				launch["same_line"] = stage._player.state["node_id"] == first
				launch["text"] = stage._terms_panel.get_child(0).get_child(1).get_child(0).text
				launch["button"] = stage._terms_button.text
				stage._terms_button.pressed.emit()
				await process_frame
				await process_frame
				launch["accepted"] = {"open": stage._terms_open(), "clip": stage.current_voice(),
					"playing": stage._voice_player.playing}
			stage._toolbar("License")
			await process_frame
			launch["reread"] = {"open": stage._terms_open(), "required": stage._terms_required,
				"button": stage._terms_button.text}
			stage._unhandled_key_input(_key(KEY_ESCAPE))
			await process_frame
			launch["escape_closes_reread"] = not stage._terms_open()
			launch["stored"] = FileAccess.file_exists("user://flint_graph/terms-" + checked["story"]["id"] + ".json")
			launches.append(launch)
			stage.queue_free()
			await process_frame
		print("UI_RESULT:" + JSON.stringify(launches))
		quit(0)
		return
	if config["case"] in ["voice", "voice_preview"]:
		# Voiced lines (ADR 0043): what plays on each screen, the volume and its storage.
		var view_script: GDScript = load("res://preview/vn_view.gd" if config["case"] == "voice_preview" else "res://runtime/vn_view.gd")
		var parsed: Array = []
		for encoded: String in config.get("wav_cases", []):
			var stream: AudioStreamWAV = view_script.wav_stream(Marshalls.base64_to_raw(encoded))
			parsed.append(null if stream == null else {"rate": stream.mix_rate, "stereo": stream.stereo, "bytes": stream.data.size()})
		var stage: Control = view_script.new()
		root.add_child(stage)
		stage.size = Vector2(1280, 720)
		stage.configure(checked["story"], checked["package_hash"], checked["assets"])
		stage._set_text_speed("instant")
		stage._set_reduced_motion(true)
		await process_frame
		await process_frame
		var clips: Array = [stage.current_voice()]
		var playing: Array = [stage._voice_player.playing]
		for step in range(3):
			_find(stage, "Continue").pressed.emit()
			await process_frame
			clips.append(stage.current_voice())
			playing.append(stage._voice_player.playing)
		stage._volume_slider.value = 30
		await process_frame
		var db: float = stage._voice_player.volume_db
		stage._toolbar("Restart")
		await process_frame
		var restarted: Variant = stage.current_voice()
		stage._toolbar("Gallery")
		await process_frame
		var gallery_open: bool = stage._gallery_panel.visible
		stage._close_gallery()
		print("UI_RESULT:" + JSON.stringify({"parsed": parsed, "clips": clips, "playing": playing,
			"volume": stage._voice_volume, "volume_db": db, "restarted": restarted, "gallery_open": gallery_open,
			"stored": FileAccess.file_exists("user://flint_graph/settings.json"),
			"stored_volume": load("res://runtime/save_store.gd").read_voice_volume()}))
		quit(0)
		return
	if config["case"] in ["voice_gate", "voice_gate_preview"]:
		# A browser that may not start sound yet: a start screen, then the first clip.
		var base := "res://preview/vn_view.gd" if config["case"] == "voice_gate_preview" else "res://runtime/vn_view.gd"
		var muted := GDScript.new()
		muted.source_code = "extends \"%s\"\nfunc _sound_blocked() -> bool:\n\treturn true\n" % base
		muted.reload()
		var states: Dictionary = {}
		for flow: String in ["click", "key", "silent", "allowed"]:
			var story: Dictionary = checked["story"].duplicate(true)
			if flow == "silent":
				for node: Dictionary in story["nodes"].values():
					node.erase("voice")
			var stage: Control = (load(base) if flow == "allowed" else muted).new()
			root.add_child(stage)
			stage.size = Vector2(1280, 720)
			stage.configure(story, checked["package_hash"], checked["assets"])
			stage._set_text_speed("instant")
			stage._set_reduced_motion(true)
			await process_frame
			await process_frame
			var first: String = stage._player.state["node_id"]
			var snap := func() -> Dictionary:
				return {"gate": stage._sound_gate != null and stage._sound_gate.visible, "clip": stage.current_voice(),
					"playing": stage._voice_player.playing, "same_line": stage._player.state["node_id"] == first}
			states[flow] = {"before": snap.call()}
			if flow in ["click", "key"]:
				for pressed: bool in [true, false]:
					var event: InputEvent
					if flow == "click":
						event = InputEventMouseButton.new()
						event.button_index = MOUSE_BUTTON_LEFT
						event.position = Vector2(640, 360)
					else:
						event = InputEventKey.new()
						event.keycode = KEY_ENTER
					event.pressed = pressed
					root.push_input(event)
				await process_frame
				await process_frame
				states[flow]["opened"] = snap.call()
				var enter := InputEventKey.new()
				enter.keycode = KEY_ENTER
				enter.pressed = true
				root.push_input(enter)
				enter = enter.duplicate()
				enter.pressed = false
				root.push_input(enter)
				await process_frame
				states[flow]["next"] = snap.call()
			stage.queue_free()
			await process_frame
		print("UI_RESULT:" + JSON.stringify(states))
		quit(0)
		return
	if config["case"] in ["cg_gallery", "cg_preview"]:
		var preview: bool = config["case"] == "cg_preview"
		var script: GDScript = load("res://preview/vn_view.gd" if preview else "res://runtime/vn_view.gd")
		var stage: Control = script.new()
		root.add_child(stage)
		stage.size = Vector2(1280, 720)
		stage.configure(checked["story"], checked["package_hash"], checked["assets"])
		stage._set_text_speed("instant")
		stage._set_reduced_motion(true)
		stage._toolbar("Save")  # Save before seeing a CG.
		_find(stage, "Continue").pressed.emit()
		await process_frame
		var overlay: bool = stage._cg.texture != null and stage._cg.size == Vector2(1280, 720)
		var above: bool = stage._cg.get_index() > stage._figures.get_index() and stage._box.get_index() > stage._cg.get_index()
		_find(stage, "Gallery").pressed.emit()
		var locked: Button = _find(stage._gallery_panel, "CG 2 · Locked")
		var disabled: bool = locked != null and locked.disabled
		var before: Dictionary = stage._player.state
		stage._action("advance", stage._player.generation, stage._player)
		stage._toolbar("Restart")
		stage._toolbar("Load")
		var pauses: bool = stage._player.state == before
		pauses = pauses and _find(stage, "Restart").disabled and _find(stage, "Continue").disabled
		_find(stage._gallery_panel, "CG 1").pressed.emit()
		var viewed: bool = stage._gallery_image.texture != null
		_find(stage._gallery_panel, "Close gallery").pressed.emit()
		stage._toolbar("Load")
		var retained_load: bool = stage._player.gallery[0]["unlocked"]
		stage._toolbar("Restart")
		var retained: bool = stage._player.gallery[0]["unlocked"]
		var disk: bool = FileAccess.file_exists(stage._gallery_path())
		var fresh: Control = script.new()
		root.add_child(fresh)
		fresh.size = Vector2(1280, 720)
		fresh.configure(checked["story"], checked["package_hash"], checked["assets"])
		var unlocked: bool = fresh._player.gallery[0]["unlocked"]
		for action: String in ["advance", "advance", "choose:stay"]:
			stage._action(action, stage._player.generation, stage._player)
		var cleared: bool = stage._cg.texture == null and stage._background.texture != null and not stage._sprites.is_empty()
		print("UI_RESULT:" + JSON.stringify({"overlay": overlay, "dialogue_above": above,
			"cover": stage._cg.stretch_mode == TextureRect.STRETCH_KEEP_ASPECT_COVERED,
			"locked_disabled": disabled, "gallery_pauses": pauses, "view_unlocked": viewed,
			"retained_on_restart": retained, "retained_on_load": retained_load, "disk_exists": disk,
			"fresh_unlocked": unlocked, "cleared": cleared}))
		quit(0)
		return
	if config["case"] == "stage_layout":
		# The headless window keeps its own size, so the view is sized explicitly.
		var stage: Control = load("res://runtime/vn_view.gd").new()
		root.add_child(stage)
		stage.size = Vector2(1280, 720)
		stage.configure(checked["story"], checked["package_hash"], checked["assets"])
		stage._set_text_speed("instant")
		stage._set_reduced_motion(true)
		var screens: Array = []
		for step: String in ["", "Continue", "Go", "Continue"]:
			if step != "":
				_find(stage, step).pressed.emit()
			await process_frame
			await process_frame
			var figures: Array = []
			for figure: Node in stage._figures.get_children():
				if figure is TextureRect and not figure.is_queued_for_deletion():
					var rect: Rect2 = figure.get_global_rect()
					figures.append({"position": figure.get_meta("position"), "x": rect.position.x,
						"bottom": rect.end.y, "width": rect.size.x, "height": rect.size.y})
			var box: Rect2 = stage._box.get_global_rect()
			var labels: Array = []
			for button: Button in stage._buttons:
				labels.append(button.text)
			screens.append({"text": _body(stage), "buttons": labels, "figures": figures,
				"background": stage._background.texture != null,
				"name": stage._name.text if stage._name_box.visible else null,
				"box": {"left": box.position.x, "right": box.end.x, "bottom": box.end.y, "top": box.position.y}})
		print("UI_RESULT:" + JSON.stringify({"screens": screens}))
		quit(0)
		return
	if config["case"] == "controls":
		await _probe_controls(checked)
		quit(0)
		return
	if config["case"] == "transitions":
		await _probe_transitions(checked)
		quit(0)
		return
	if config["case"] == "controls_settings":
		_probe_settings()
		quit(0)
		return
	if config["case"] == "controls_preview":
		await _probe_controls_preview(checked)
		quit(0)
		return
	if config["case"] == "stale_restart":
		root.size = Vector2i(1280, 900)
		var view: Control = load("res://runtime/game_view.gd").new()
		root.add_child(view)
		view.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		view.configure(checked["story"], checked["package_hash"], checked["assets"])
		await process_frame
		var before := _body(view)
		var stale := _find(view, "Continue")
		_find(view, "Restart").pressed.emit()
		stale.pressed.emit() # Replay a queued signal before its old control is freed.
		print("UI_RESULT:" + JSON.stringify({"preserved": _body(view) == before}))
		quit(0)
		return
	if not FileAccess.file_exists("res://runtime/save_store.gd"):
		print("UI_RESULT:" + JSON.stringify({"error": "missing_save_store"}))
		quit(1)
		return
	var store: GDScript = load("res://runtime/save_store.gd")
	var player: RefCounted = load("res://runtime/player.gd").new(checked["story"], checked["package_hash"])
	var old: PackedByteArray = player.save()
	player.act("advance")
	var updated: PackedByteArray = player.save()
	var first: String = store.write_save(checked["package_hash"], old)
	var results: Array = []
	for mode: String in ["write", "verify", "replace"]:
		var error: String = store.write_save(checked["package_hash"], updated, FaultIO.new(mode))
		var after: Dictionary = store.read_save(checked["package_hash"])
		results.append({"error": error, "preserved": after.get("data") == old})
	var second: String = store.write_save(checked["package_hash"], updated)
	var final: Dictionary = store.read_save(checked["package_hash"])
	print("UI_RESULT:" + JSON.stringify({"first": first, "failures": results,
		"second": second, "updated": final.get("data") == updated}))
	quit(0)


func _controls_stage(base: String, checked: Dictionary) -> Control:
	var stage: Control = load(base).new()
	root.add_child(stage)
	stage.size = Vector2(1280, 720)
	stage.configure(checked["story"], checked["package_hash"], checked["assets"])
	await process_frame
	return stage


func _node_of(stage: Control) -> String:
	return stage._player.state["node_id"]


func _dimmed(stage: Control) -> Dictionary:
	return {"mira": stage._sprites["mira"].modulate != Color.WHITE,
		"oren": stage._sprites["oren"].modulate != Color.WHITE}


func _mouse(button: int) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button
	event.pressed = true
	return event


func _probe_controls(checked: Dictionary) -> void:
	var out := {}
	var store: GDScript = load("res://runtime/save_store.gd")
	var stage: Control = await _controls_stage("res://runtime/vn_view.gd", checked)
	var next := _find(stage, "Continue")
	out["default_speed"] = stage._settings["text_speed"]
	out["revealing_at_start"] = stage._revealing()
	next.pressed.emit()
	out["first_press"] = {"node": _node_of(stage), "revealing": stage._revealing()}
	next.pressed.emit()
	out["second_press"] = {"node": _node_of(stage), "revealing": stage._revealing()}
	stage._set_text_speed("instant")
	out["instant_stops_the_reveal"] = not stage._revealing()
	# Speaker focus: Oren speaks on l2, Mira on l1, nobody on l3.
	var focus := {"oren_speaks": _dimmed(stage)}
	stage._toolbar("Restart")
	focus["mira_speaks"] = _dimmed(stage)
	stage._request_advance()
	stage._request_advance()
	focus["narration"] = _dimmed(stage)
	stage._toolbar("Restart")
	stage._set_speaker_focus(false)
	focus["turned_off"] = _dimmed(stage)
	stage._set_speaker_focus(true)
	out["focus"] = focus
	# Read to the last line, then open the backlog.
	stage._request_advance()
	stage._request_advance()
	stage._request_advance()
	_find(stage, "Stay").pressed.emit()
	var log := {}
	stage._toolbar("Log")
	await process_frame
	await process_frame
	log["entries"] = stage.backlog_rows()
	var before := _node_of(stage)
	stage._request_advance()
	log["pauses"] = {"advanced": _node_of(stage) != before,
		"continue_disabled": _find(stage, "Continue").disabled}
	stage._unhandled_key_input(_key(KEY_ESCAPE))
	log["escape_closes"] = not stage._log_panel.visible
	for index in range(400):
		stage._note_backlog(null, str(index))
	log["limit"] = stage._backlog.size()
	out["log"] = log
	# Auto, from the start of the story.
	stage._toolbar("Restart")
	var auto := {}
	stage._toolbar("Auto")
	stage._process(0.5)
	auto["before_delay"] = _node_of(stage)
	stage._process(60.0)
	auto["after_delay"] = _node_of(stage)
	stage._toolbar("Log")
	stage._process(60.0)
	auto["paused_by_log"] = _node_of(stage)
	stage._close_log()
	stage._process(60.0)
	stage._process(60.0)
	stage._process(60.0)
	stage._process(60.0)
	auto["stops_at_choice"] = _node_of(stage)
	auto["still_on"] = stage._auto
	stage._toolbar("Auto")
	out["auto"] = auto
	# Skip: l1 to l3 were read above; the line after the choice is made unread again.
	stage._read.erase(load("res://runtime/reading.gd").read_mark("l4", "A line [b]nobody[/b] has read."))
	stage._toolbar("Restart")
	var skip := {}
	stage._toolbar("Skip")
	for tick in range(8):
		stage._process(1.0)
	skip["stops_at"] = _node_of(stage)
	skip["turned_off_at_choice"] = not stage._skip
	_find(stage, "Stay").pressed.emit()
	stage._toolbar("Skip")
	stage._process(1.0)
	skip["unread"] = {"node": _node_of(stage), "skip": stage._skip}
	var reading: GDScript = load("res://runtime/reading.gd")
	skip["changed_text_is_unread"] = reading.read_mark("l1", "One") != reading.read_mark("l1", "Two")
	out["skip"] = skip
	# Hide: back at the first line.
	stage._toolbar("Restart")
	var hide := {}
	stage._toolbar("Hide")
	hide["hidden"] = {"box": stage._box.visible, "toolbar": stage._menu.visible}
	stage._input(_mouse(MOUSE_BUTTON_LEFT))
	hide["after_click"] = {"box": stage._box.visible, "toolbar": stage._menu.visible, "node": _node_of(stage)}
	stage._toolbar("Hide")
	stage._input(_key(KEY_ENTER))
	var release := _key(KEY_ENTER)
	release.pressed = false
	stage._input(release)
	hide["after_enter"] = {"box": stage._box.visible, "toolbar": stage._menu.visible, "node": _node_of(stage)}
	stage._gui_input(_mouse(MOUSE_BUTTON_RIGHT))
	hide["after_right_click"] = {"box": stage._box.visible}
	stage._set_ui_hidden(false)
	out["hide"] = hide
	# Quick save has its own slot.
	var quick := {}
	stage._toolbar("Save")
	var regular: Dictionary = store.read_save(checked["package_hash"])
	stage._request_advance()
	stage._toolbar("Quick save")
	quick["slot_written"] = store.read_quick_save(checked["package_hash"]).get("error") == ""
	quick["regular_untouched"] = store.read_save(checked["package_hash"]).get("data") == regular.get("data")
	stage._request_advance()
	stage._request_advance()
	stage._toolbar("Quick load")
	quick["loaded_node"] = _node_of(stage)
	quick["notice"] = stage._notice.text
	quick["log_marks_the_load"] = stage.backlog_rows()[-2] == [null, "— Quick save loaded —"]
	out["quick"] = quick
	# The menu pauses the story and holds the rest of the actions.
	var menu := {}
	stage._toolbar("Menu")
	menu["open"] = stage._menu_panel.visible
	menu["continue_disabled"] = _find(stage, "Continue").disabled
	var bar: Array = []
	for button: Node in stage._menu.get_children():
		bar.append(button.text)
	menu["toolbar_buttons"] = bar
	stage._unhandled_key_input(_key(KEY_ESCAPE))
	menu["escape_closes"] = not stage._menu_panel.visible
	out["menu"] = menu
	# Settings persist on this device.
	stage._set_text_speed("slow")
	stage._set_auto_speed("fast")
	stage._set_speaker_focus(false)
	stage._volume_slider.value = 40
	await process_frame
	out["stored"] = store.read_settings()
	stage._flush_read_marks(100.0)
	out["read_marks_kept"] = store.read_marks(checked["story"]["id"]).size() > 0
	print("UI_RESULT:" + JSON.stringify(out))


func _probe_settings() -> void:
	var store: GDScript = load("res://runtime/save_store.gd")
	var out := {}
	DirAccess.make_dir_recursive_absolute("user://flint_graph")
	var old := FileAccess.open("user://flint_graph/settings.json", FileAccess.WRITE)
	old.store_string("{\"schema_version\":\"1\",\"voice_volume\":35}")
	old.close()
	out["old_file"] = store.read_settings()
	var bad := FileAccess.open("user://flint_graph/settings.json", FileAccess.WRITE)
	bad.store_string("{\"schema_version\":\"2\",\"voice_volume\":900,\"text_speed\":\"warp\"}")
	bad.close()
	out["bad_file"] = store.read_settings()
	print("UI_RESULT:" + JSON.stringify(out))


func _list_user_files() -> Array:
	var found: Array = []
	var pending: Array = ["user://flint_graph"]
	while not pending.is_empty():
		var folder: String = pending.pop_back()
		var access := DirAccess.open(folder)
		if access == null:
			continue
		for name in access.get_files():
			found.append(folder.path_join(name))
		for name in access.get_directories():
			pending.append(folder.path_join(name))
	return found


func _probe_controls_preview(checked: Dictionary) -> void:
	var out := {}
	var before := _list_user_files()
	var spy := GDScript.new()
	spy.source_code = "extends \"res://preview/vn_view.gd\"\nvar calls: Array = []\nfunc _overlay_bridge(open: bool) -> void:\n\tcalls.append(open)\n"
	spy.reload()
	var stage: Control = spy.new()
	root.add_child(stage)
	stage.size = Vector2(1280, 720)
	stage.configure(checked["story"], checked["package_hash"], checked["assets"])
	await process_frame
	var disabled := {}
	for label: String in ["Save", "Load", "Quick save", "Quick load", "Restart", "Gallery"]:
		disabled[label] = _find(stage, label).disabled
	out["disabled"] = disabled
	stage._set_text_speed("instant")
	out["speed_changes"] = stage._settings["text_speed"]
	stage._toolbar("Log")
	await process_frame
	out["log_works"] = stage._log_panel.visible
	stage._close_log()
	stage._toolbar("Menu")
	await process_frame
	stage._close_menu()
	stage._request_advance()
	stage._request_advance()
	stage._request_advance()
	stage._toolbar("Restart")
	stage._toolbar("Skip")
	for tick in range(8):
		stage._process(1.0)
	out["skip_works_in_memory"] = _node_of(stage)
	stage._flush_read_marks(100.0)
	var written: Array = []
	for path: String in _list_user_files():
		if not path in before:
			written.append(path)
	out["files_written"] = written
	out["overlay_calls"] = stage.calls
	print("UI_RESULT:" + JSON.stringify(out))


func _settle_screen(stage: Control) -> void:
	stage._process(30.0)
	stage._process(30.0)
	await process_frame


func _screen_of(stage: Control) -> Dictionary:
	var figures: Array = []
	for id: String in stage._sprites:
		figures.append([id, stage._sprites[id].position, stage._sprites[id].size])
	var background: Texture2D = stage._background.texture
	return {"node": _node_of(stage), "background": background.get_size() if background != null else null,
		"figures": figures, "text": stage._text.text}


func _walk_to(stage: Control, node: String) -> void:
	for step in range(40):
		if _node_of(stage) == node:
			return
		await _settle_screen(stage)
		stage._request_advance()


func _probe_transitions(checked: Dictionary) -> void:
	var out := {}
	var stage: Control = await _controls_stage("res://runtime/vn_view.gd", checked)
	stage._set_text_speed("instant")
	var names := ["", "dissolve", "fade", "slide", "cut", "soft", "", ""]
	var presentation: Array = []
	var ran := {}
	var leftovers: Array = []
	var screens: Array = []
	for index in range(8):
		var current: Dictionary = stage._player.view
		presentation.append([current["transition"], current["effect"]])
		if names[index] != "":
			ran[names[index]] = stage._transitioning()
		await _settle_screen(stage)
		if stage._leaving != null or stage._curtain.color.a != 0.0 or stage._flash.color.a != 0.0 or stage._stage_root.position != Vector2.ZERO:
			leftovers.append(index)
		screens.append(_screen_of(stage))
		stage._request_advance()
	out["presentation"] = presentation
	out["ran"] = ran
	out["settled_leftovers"] = leftovers
	# A press during a transition, and a save during one.
	stage._toolbar("Restart")
	await _walk_to(stage, "l1")
	await _settle_screen(stage)
	stage._request_advance()
	var saved: Dictionary = JSON.parse_string(stage._player.save().get_string_from_utf8())
	out["save_mid_transition"] = {"node": saved["node_id"], "background": saved["stage"]["background"]}
	stage._request_advance()
	out["press_finishes"] = {"node": _node_of(stage), "transitioning": stage._transitioning()}
	# Auto waits for a transition.
	stage._toolbar("Restart")
	await _walk_to(stage, "l1")
	await _settle_screen(stage)
	stage._request_advance()
	stage._toolbar("Auto")
	stage._process(0.2)
	out["auto_waits"] = {"during": _node_of(stage), "transitioning_then": stage._transitioning()}
	stage._toolbar("Auto")
	# Shake and flash.
	await _walk_to(stage, "l6")
	var shake := {}
	stage._process(0.1)
	shake["moved"] = stage._stage_root.position != Vector2.ZERO
	stage._process(30.0)
	shake["settled_at_origin"] = stage._stage_root.position == Vector2.ZERO
	out["shake"] = shake
	stage._request_advance()
	var flash := {}
	stage._process(0.05)
	var first: float = stage._flash.color.a
	flash["visible"] = first > 0.0
	stage._process(0.1)
	var second: float = stage._flash.color.a
	stage._process(0.1)
	var third: float = stage._flash.color.a
	flash["once"] = first > second and second > third
	stage._process(30.0)
	flash["settled_clear"] = stage._flash.color.a == 0.0
	out["flash"] = flash
	# Restart and Load are cuts.
	stage._toolbar("Restart")
	stage._toolbar("Save")
	await _walk_to(stage, "l1")
	await _settle_screen(stage)
	stage._request_advance()
	stage._toolbar("Restart")
	out["restart_transitioned"] = stage._transitioning()
	await _walk_to(stage, "l1")
	stage._toolbar("Load")
	out["load_transitioned"] = stage._transitioning()
	# Skip shows none of it: everything up to l6 was read above.
	stage._toolbar("Restart")
	stage._toolbar("Skip")
	var skipped := false
	for tick in range(12):
		stage._process(1.0)
		skipped = skipped or stage._transitioning()
	out["skip_transitioned"] = skipped
	root.remove_child(stage)
	stage.queue_free()
	# Reduced motion: the same screens, with nothing moving.
	var calm: Control = await _controls_stage("res://runtime/vn_view.gd", checked)
	calm._set_text_speed("instant")
	calm._set_reduced_motion(true)
	var reduced := {"transitioned": false, "shook": false, "flashed": false}
	var calm_screens: Array = []
	for index in range(8):
		reduced["transitioned"] = reduced["transitioned"] or calm._transitioning()
		calm._process(0.05)
		reduced["shook"] = reduced["shook"] or calm._stage_root.position != Vector2.ZERO
		reduced["flashed"] = reduced["flashed"] or calm._flash.color.a != 0.0
		await _settle_screen(calm)
		calm_screens.append(_screen_of(calm))
		calm._request_advance()
	out["reduced"] = reduced
	out["settled_screens_match"] = var_to_str(screens) == var_to_str(calm_screens)
	out["stored_reduced_motion"] = load("res://runtime/save_store.gd").read_settings()["reduced_motion"]
	print("UI_RESULT:" + JSON.stringify(out))
