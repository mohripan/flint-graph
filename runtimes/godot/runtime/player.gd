# SPDX-License-Identifier: MIT
# Reference-compatible v1 state machine. Source is a validated compiler snapshot.
extends RefCounted

const StrictJson = preload("res://runtime/strict_json.gd")
const SAVE_LIMIT := 6291456
var _story: Dictionary
var _package_hash: String
var _variables: Dictionary = {}
var _node_id: String
var _status := "playing"
var _ending: Variant = null
var _fault: Variant = null
var _generation := 0

var generation: int:
	get:
		return _generation

var state: Dictionary:
	get:
		return {"package_hash": _package_hash, "node_id": _node_id,
			"variables": _variables.duplicate(true), "status": _status,
			"ending": _ending, "fault": _fault}

var view: Dictionary:
	get:
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


func _init(source: Dictionary, content_hash: String) -> void:
	_story = source.duplicate(true)
	_package_hash = content_hash
	for key: String in _story["variables"]:
		_variables[key] = _story["variables"][key]["initial"]
	_settle(_story["entry"])


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
	_generation += 1
	return ""


func frame(action: Variant = null) -> Dictionary:
	var current := view
	var option_ids: Array = []
	for option: Dictionary in current["options"]:
		option_ids.append(option["id"])
	return {"action": action, "node_id": _node_id, "text_id": current["text_id"],
		"option_ids": option_ids, "variables": _variables.duplicate(true),
		"status": _status, "ending": _ending, "fault": _fault}


func save() -> PackedByteArray:
	var saved := state
	saved["schema_version"] = "1"
	return JSON.stringify(saved, "", true).to_utf8_buffer()


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
	if saved.size() != required.size():
		return "invalid_save"
	for key: String in required:
		if not saved.has(key):
			return "invalid_save"
	if not saved["schema_version"] is String or saved["schema_version"] != "1":
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
			"automatic_transition_limit": valid = kind in ["set", "branch"]
			"integer_overflow": valid = kind == "set" and not _assigned(node, saved["variables"])["ok"]
	if not valid:
		return "invalid_save"
	_node_id = saved["node_id"]
	_variables = saved["variables"].duplicate(true)
	_status = saved["status"]
	_ending = saved["ending"]
	_fault = saved["fault"]
	_generation += 1
	return ""
