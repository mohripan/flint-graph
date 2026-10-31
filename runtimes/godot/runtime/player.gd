# SPDX-License-Identifier: MIT
# Reference-compatible v1 and v2 state machine. Source is a validated compiler snapshot.
# v2 (ADR 0040) adds a persistent stage: a background and characters in three slots.
extends RefCounted

const StrictJson = preload("res://runtime/strict_json.gd")
const SAVE_LIMIT := 6291456
const POSITIONS := ["left", "center", "right"]
var _story: Dictionary
var _package_hash: String
var _variables: Dictionary = {}
var _node_id: String
var _status := "playing"
var _ending: Variant = null
var _fault: Variant = null
var _generation := 0
var _v2 := false
var _stage: Dictionary = {"background": null, "cg": null, "characters": []}
var _cg_assets: Array = []
var _seen_cgs: Dictionary = {}

var gallery: Array:
	get:
		var entries: Array = []
		for id: String in _cg_assets:
			entries.append({"id": id, "unlocked": _seen_cgs.has(id)})
		return entries

var seen_cgs: Array:
	get:
		var ids: Array = []
		for id: String in _cg_assets:
			if _seen_cgs.has(id):
				ids.append(id)
		return ids

var generation: int:
	get:
		return _generation

var state: Dictionary:
	get:
		var current := {"package_hash": _package_hash, "node_id": _node_id,
			"variables": _variables.duplicate(true), "status": _status,
			"ending": _ending, "fault": _fault}
		if _v2:
			current["stage"] = _stage.duplicate(true)
		return current

var view: Dictionary:
	get:
		if _v2:
			return _view_v2()
		if _status == "fault":
			return {"type": "fault", "text_id": null, "text": "The game cannot continue.",
				"speaker": null, "speaker_name": null, "background": null,
				"portrait": null, "options": []}
		var node: Dictionary = _story["nodes"][_node_id]
		var speaker: Variant = node.get("speaker") if node["type"] == "line" else null
		var options: Array = []
		for option: Dictionary in _visible(node, _variables):
			options.append({"id": option["id"], "text_id": option["text_id"], "text": option["text"]})
		return {"type": node["type"], "text_id": node["text_id"], "text": node["text"],
			"speaker": speaker,
			"speaker_name": _story["characters"][speaker]["name"] if speaker != null else null,
			"background": node.get("background") if node["type"] == "line" else null,
			"portrait": node.get("portrait") if node["type"] == "line" else null,
			"options": options}


func _view_v2() -> Dictionary:
	# The screen is the current text plus the persistent stage, including faults.
	if _status == "fault":
		return {"type": "fault", "text_id": null, "text": "The game cannot continue.",
			"speaker": null, "speaker_name": null, "speaker_color": null,
			"stage": _stage.duplicate(true), "voice": null, "options": []}
	var node: Dictionary = _story["nodes"][_node_id]
	var speaker: Variant = node.get("speaker") if node["type"] == "line" else null
	var character: Variant = _story["characters"][speaker] if speaker != null else null
	var options: Array = []
	for option: Dictionary in _visible(node, _variables):
		options.append({"id": option["id"], "text_id": option["text_id"], "text": option["text"]})
	return {"type": node["type"], "text_id": node["text_id"], "text": node["text"],
		"speaker": speaker,
		"speaker_name": character["name"] if character != null else null,
		"speaker_color": character.get("color") if character != null else null,
		"stage": _stage.duplicate(true), "voice": _voice(node), "options": options}


func _voice(node: Dictionary) -> Variant:
	# The settled line's clip (ADR 0043); a voice without audio stays silent.
	if node["type"] != "line" or not node.get("voice") is Dictionary:
		return null
	return node["voice"].get("audio")


func _init(source: Dictionary, content_hash: String, unlocked: Array = []) -> void:
	_story = source.duplicate(true)
	_package_hash = content_hash
	_v2 = _story["schema_version"] == "2"
	_cg_assets = cg_gallery_assets(_story)
	for id: Variant in unlocked:
		if id is String and id in _cg_assets:
			_seen_cgs[id] = true
	for key: String in _story["variables"]:
		_variables[key] = _story["variables"][key]["initial"]
	_settle(_story["entry"])
	_unlock_cg()


static func cg_gallery_assets(story: Dictionary) -> Array:
	if story["schema_version"] != "2":
		return []
	var nodes: Dictionary = story["nodes"]
	var pending: Array = nodes.keys()
	pending.sort()
	pending.reverse()
	pending.append(story["entry"])
	var visited := {}
	var assets: Array = []
	while not pending.is_empty():
		var key: String = pending.pop_back()
		if visited.has(key):
			continue
		visited[key] = true
		var node: Dictionary = nodes[key]
		if node["type"] == "stage" and node.get("cg") != null and not node["cg"] in assets:
			assets.append(node["cg"])
		var targets: Array = []
		match node["type"]:
			"line", "stage", "set": targets.append(node["next"])
			"choice":
				for option: Dictionary in node["options"]:
					targets.append(option["target"])
			"branch": targets = [node["if_true"], node["if_false"]]
		targets.reverse()
		pending.append_array(targets)
	return assets


func _unlock_cg() -> void:
	if _stage["cg"] in _cg_assets:
		_seen_cgs[_stage["cg"]] = true


func _staged(node: Dictionary) -> Dictionary:
	# Apply one stage node to a copy: hide, then show (a slot holds one character).
	var background: Variant = node["background"] if node.has("background") else _stage["background"]
	var hidden: Array = node.get("hide", [])
	var present := {}
	for item: Dictionary in _stage["characters"]:
		if not item["id"] in hidden:
			present[item["id"]] = item.duplicate()
	for entry: Dictionary in node.get("show", []):
		for other: String in present.keys():
			if present[other]["position"] == entry["position"] and other != entry["character"]:
				present.erase(other)
		present[entry["character"]] = {"id": entry["character"], "sprite": entry["sprite"],
			"position": entry["position"]}
		if entry.has("x"):
			present[entry["character"]]["x"] = entry["x"]  # This placement's own horizontal place.
	var ordered: Array = []
	for position: String in POSITIONS:
		for item: Dictionary in present.values():
			if item["position"] == position:
				ordered.append(item)
	return {"background": background, "cg": node.get("cg", _stage["cg"]), "characters": ordered}


func _expressed(speaker: String, expression: String) -> Dictionary:
	var updated := _stage.duplicate(true)
	for item: Dictionary in updated["characters"]:
		if item["id"] == speaker:
			item["sprite"] = expression
	return updated


func _condition(condition: Dictionary, variables: Dictionary) -> bool:
	var op: String = condition["op"]
	if op == "all":
		for child: Dictionary in condition["children"]:
			if not _condition(child, variables):
				return false
		return true
	if op == "any":
		for child: Dictionary in condition["children"]:
			if _condition(child, variables):
				return true
		return false
	if op == "not":
		return not _condition(condition["child"], variables)
	var left: Variant = variables[condition["variable"]]
	var right: Variant = condition["value"]
	match op:
		"eq": return left == right
		"ne": return left != right
		"lt": return left < right
		"le": return left <= right
		"gt": return left > right
	return left >= right


func _visible(node: Dictionary, variables: Dictionary) -> Array:
	var options: Array = []
	if node["type"] == "choice":
		for option: Dictionary in node["options"]:
			if not option.has("condition") or _condition(option["condition"], variables):
				options.append(option)
	return options


func _assigned(node: Dictionary, variables: Dictionary) -> Dictionary:
	var updated := variables.duplicate(true)
	for operation: Dictionary in node["operations"]:
		var key: String = operation["variable"]
		var value: Variant = operation["value"]
		if operation["op"] == "increment":
			value += updated[key]
			if value < -2147483648 or value > 2147483647:
				return {"ok": false}
		updated[key] = value
	return {"ok": true, "value": updated}


func _settle(target: String) -> void:
	var transitions := 0
	_status = "playing"
	_ending = null
	_fault = null
	while true:
		_node_id = target
		var node: Dictionary = _story["nodes"][target]
		var kind: String = node["type"]
		if kind in ["line", "choice"]:
			if kind == "choice" and _visible(node, _variables).is_empty():
				_status = "fault"
				_fault = "no_available_choices"
			if kind == "line" and node.has("expression"):
				# Applied once when the line settles; saves store the result.
				_stage = _expressed(node["speaker"], node["expression"])
			return
		if kind == "end":
			_status = "ended"
			_ending = node["ending"]
			return
		if transitions >= 1000:
			_status = "fault"
			_fault = "automatic_transition_limit"
			return
		transitions += 1
		if kind == "branch":
			target = node["if_true"] if _condition(node["condition"], _variables) else node["if_false"]
		elif kind == "stage":
			_stage = _staged(node)
			target = node["next"]
		else:
			var assigned := _assigned(node, _variables)
			if not assigned["ok"]:
				_status = "fault"
				_fault = "integer_overflow"
				return
			_variables = assigned["value"]
			target = node["next"]


func act(action: Variant, expected_generation: Variant = null) -> String:
	if _status != "playing" or not action is String:
		return "invalid_action"
	if expected_generation != null and (typeof(expected_generation) != TYPE_INT or expected_generation != _generation):
		return "invalid_action"
	var node: Dictionary = _story["nodes"][_node_id]
	var target := ""
	if action == "advance" and node["type"] == "line":
		target = node["next"]
	elif action.begins_with("choose:") and node["type"] == "choice":
		for option: Dictionary in _visible(node, _variables):
			if option["id"] == action.substr(7):
				target = option["target"]
	if target == "":
		return "invalid_action"
	_settle(target)
	_unlock_cg()
	_generation += 1
	return ""


func frame(action: Variant = null) -> Dictionary:
	var current := view
	var option_ids: Array = []
	for option: Dictionary in current["options"]:
		option_ids.append(option["id"])
	var result := {"action": action, "node_id": _node_id, "text_id": current["text_id"],
		"option_ids": option_ids, "variables": _variables.duplicate(true),
		"status": _status, "ending": _ending, "fault": _fault}
	if _v2:
		result["stage"] = _stage.duplicate(true)
		result["voice"] = current["voice"]
	return result


func save() -> PackedByteArray:
	var saved := state
	saved["schema_version"] = "2" if _v2 else "1"
	return JSON.stringify(saved, "", true).to_utf8_buffer()


func _checked_stage(value: Variant) -> Variant:
	# A saved stage: known image background and characters in canonical slots.
	if not value is Dictionary or value.size() != (3 if value.has("cg") else 2) or not value.has("background") or not value.has("characters"):
		return null
	var background: Variant = value["background"]
	var assets: Dictionary = _story["assets"]
	var cg: Variant = value.get("cg")
	if cg != null and (not cg is String or not assets.has(cg) or assets[cg]["kind"] != "image"):
		return null
	if background != null and (not background is String or not assets.has(background) or assets[background]["kind"] != "image"):
		return null
	var characters: Variant = value["characters"]
	if not characters is Array or characters.size() > POSITIONS.size():
		return null
	var seen := {}
	var last := -1
	for item: Variant in characters:
		if not item is Dictionary or item.size() != (4 if item.has("x") else 3) or not item.has("id") or not item.has("sprite") or not item.has("position"):
			return null
		if item.has("x") and (typeof(item["x"]) != TYPE_INT or item["x"] < 0 or item["x"] > 100):
			return null
		if not item["id"] is String or not _story["characters"].has(item["id"]) or seen.has(item["id"]):
			return null
		var sprites: Dictionary = _story["characters"][item["id"]].get("sprites", {})
		if not item["sprite"] is String or not sprites.has(item["sprite"]):
			return null
		var index: int = POSITIONS.find(item["position"]) if item["position"] is String else -1
		if index <= last:
			return null  # Unique positions, left to right.
		seen[item["id"]] = true
		last = index
	var normalized: Dictionary = value.duplicate(true)
	normalized["cg"] = cg  # Saves from runtime <= 0.4.0 omit it.
	return normalized


func _typed(value: Variant, declaration: Dictionary) -> bool:
	match declaration["type"]:
		"bool": return typeof(value) == TYPE_BOOL
		"int": return typeof(value) == TYPE_INT and value >= -2147483648 and value <= 2147483647
		"enum": return value is String and value in declaration["values"]
	return false


func load_save(data: PackedByteArray) -> String:
	var decoded := StrictJson.decode(data, SAVE_LIMIT)
	if not decoded.get("ok", false) or not decoded["value"] is Dictionary:
		return "invalid_save"
	var saved: Dictionary = decoded["value"]
	var required := ["schema_version", "package_hash", "node_id", "variables", "status", "ending", "fault"]
	if _v2:
		required.append("stage")
	if saved.size() != required.size():
		return "invalid_save"
	for key: String in required:
		if not saved.has(key):
			return "invalid_save"
	if not saved["schema_version"] is String or saved["schema_version"] != ("2" if _v2 else "1"):
		return "invalid_save"
	var stage: Variant = _checked_stage(saved["stage"]) if _v2 else null
	if _v2 and stage == null:
		return "invalid_save"
	if not saved["package_hash"] is String or saved["package_hash"] != _package_hash:
		return "invalid_save"
	if not saved["node_id"] is String or not _story["nodes"].has(saved["node_id"]):
		return "invalid_save"
	if not saved["variables"] is Dictionary or saved["variables"].size() != _story["variables"].size():
		return "invalid_save"
	for key: String in _story["variables"]:
		if not saved["variables"].has(key) or not _typed(saved["variables"][key], _story["variables"][key]):
			return "invalid_save"
	if not saved["status"] is String:
		return "invalid_save"
	var node: Dictionary = _story["nodes"][saved["node_id"]]
	var kind: String = node["type"]
	var valid := false
	if saved["status"] == "playing" and saved["ending"] == null and saved["fault"] == null:
		valid = kind == "line" or (kind == "choice" and not _visible(node, saved["variables"]).is_empty())
	elif saved["status"] == "ended" and saved["fault"] == null:
		valid = kind == "end" and saved["ending"] is String and saved["ending"] == node["ending"]
	elif saved["status"] == "fault" and saved["ending"] == null and saved["fault"] is String:
		match saved["fault"]:
			"no_available_choices": valid = kind == "choice" and _visible(node, saved["variables"]).is_empty()
			"automatic_transition_limit": valid = kind in ["set", "branch", "stage"]
			"integer_overflow": valid = kind == "set" and not _assigned(node, saved["variables"])["ok"]
	if not valid:
		return "invalid_save"
	_node_id = saved["node_id"]
	_variables = saved["variables"].duplicate(true)
	_status = saved["status"]
	_ending = saved["ending"]
	_fault = saved["fault"]
	if _v2:
		_stage = stage
		_unlock_cg()
	_generation += 1
	return ""
