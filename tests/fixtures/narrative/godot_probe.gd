# Trusted test harness, copied only into owned qualification projects; not exported to creators.
extends SceneTree


func _initialize() -> void:
	if not FileAccess.file_exists("res://runtime/player.gd"):
		print("PROBE_RESULT:" + JSON.stringify({"error": "missing_runtime"}))
		quit(1)
		return
	var bootstrap: Node = load("res://runtime/bootstrap.gd").new()
	var checked: Dictionary = bootstrap.verify_content()
	bootstrap.free()
	if not checked.get("ok", false):
		quit(1)
		return
	var config_file := FileAccess.open("res://qualification.json", FileAccess.READ)
	if config_file == null or config_file.get_length() > 8388608:
		quit(1)
		return
	var strict: GDScript = load("res://runtime/strict_json.gd")
	var decoded: Dictionary = strict.decode(config_file.get_buffer(config_file.get_length()), 8388608)
	if not decoded.get("ok", false) or not decoded["value"] is Dictionary:
		quit(1)
		return
	var config: Dictionary = decoded["value"]
	if config.has("action_cases"):
		var results: Array = []
		for item: Dictionary in config["action_cases"]:
			var candidate: RefCounted = load("res://runtime/player.gd").new(checked["story"], checked["package_hash"])
			for action: String in item["setup"]:
				if candidate.act(action) != "":
					quit(1)
					return
			var before: Dictionary = candidate.state
			var generation: int = candidate.generation
			var error: String = candidate.act(item["action"], item.get("generation"))
			results.append({"error": error, "preserved": before == candidate.state and generation == candidate.generation})
		print("PROBE_RESULT:" + JSON.stringify({"actions": results}))
		quit(0)
		return
	if config.has("decode_inputs"):
		var results: Array = []
		for encoded: String in config["decode_inputs"]:
			results.append(strict.decode(Marshalls.base64_to_raw(encoded), 6291456))
		print("PROBE_RESULT:" + JSON.stringify({"decoded": results}))
		quit(0)
		return
	if config.has("restore_cases"):
		var results: Array = []
		for encoded: String in config["restore_cases"]:
			var candidate: RefCounted = load("res://runtime/player.gd").new(checked["story"], checked["package_hash"])
			var before: Dictionary = candidate.state
			var before_generation: int = candidate.generation
			var error: String = candidate.load_save(Marshalls.base64_to_raw(encoded))
			results.append({"error": error, "preserved": before == candidate.state,
				"generation_change": candidate.generation - before_generation})
		print("PROBE_RESULT:" + JSON.stringify({"restored": results}))
		quit(0)
		return
	var player: RefCounted = load("res://runtime/player.gd").new(checked["story"], checked["package_hash"])
	var frames: Array = [player.frame()]
	var galleries: Array = [player.gallery] if config.get("gallery", false) else []
	var saved := ""
	var restore_error := ""
	var restore_preserved := true
	if config.get("save_initial", false):
		saved = player.save().get_string_from_utf8()
		restore_error = player.load_save(saved.to_utf8_buffer())
	var actions: Variant = config.get("actions", [])
	if not actions is Array or actions.size() > 10000:
		quit(1)
		return
	var trace_bytes := 0
	for index in range(actions.size()):
		if not actions[index] is String or actions[index].length() > 80:
			quit(1)
			return
		var error: String = player.act(actions[index])
		if error != "":
			print("PROBE_RESULT:" + JSON.stringify({"error": error, "state": player.state}))
			quit(1)
			return
		var frame: Dictionary = player.frame(actions[index])
		trace_bytes += JSON.stringify(frame).to_utf8_buffer().size()
		if trace_bytes > 8388608:
			quit(1)
			return
		frames.append(frame)
		if config.get("gallery", false):
			galleries.append(player.gallery)
		if config.get("save_after", -1) == index + 1:
			saved = player.save().get_string_from_utf8()
			restore_error = player.load_save(saved.to_utf8_buffer())
	if config.has("restore"):
		var before: Dictionary = player.state
		restore_error = player.load_save(config["restore"].to_utf8_buffer())
		restore_preserved = player.state == before
	print("PROBE_RESULT:" + JSON.stringify({"frames": frames, "galleries": galleries, "state": player.state,
		"save": saved, "restore_error": restore_error, "restore_preserved": restore_preserved}))
	quit(0)
