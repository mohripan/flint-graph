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
		await process_frame
		await process_frame
		if config["case"] == "cg_keyboard_gallery":
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
