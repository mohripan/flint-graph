# SPDX-License-Identifier: MIT
# Dynamic text previews have the same bounded v1 semantics as the Python loader.
extends RefCounted
const StrictJson = preload("res://runtime/strict_json.gd")
static var _ids := RegEx.create_from_string("^[a-z][a-z0-9_-]{0,63}\\z")
static var _languages := RegEx.create_from_string("^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*\\z")

static func _fields(value: Variant, required: Array, optional: Array = []) -> bool:
	if not value is Dictionary: return false
	for key: Variant in required:
		if not value.has(key): return false
	for key: Variant in value:
		if not key in required and not key in optional: return false
	return true

static func _id(value: Variant) -> bool:
	return value is String and _ids.search(value) != null

static func _text(value: Variant) -> bool:
	if not value is String or value.is_empty() or value.length() > 16384: return false
	# Python str.strip() whitespace set, including Unicode separators.
	for index in value.length():
		var point: int = value.unicode_at(index)
		if not (point in [9, 10, 11, 12, 13, 28, 29, 30, 31, 32, 133, 160, 5760, 8232, 8233, 8239, 8287, 12288] or (point >= 8192 and point <= 8202)): return true
	return false

static func _map(value: Variant, limit: int) -> bool:
	if not value is Dictionary or value.size() > limit: return false
	for key: Variant in value:
		if not _id(key): return false
	return true

static func _list(value: Variant, limit: int) -> bool:
	return value is Array and not value.is_empty() and value.size() <= limit

static func _ref(value: Variant, targets: Dictionary) -> bool:
	return _id(value) and targets.has(value)

static func _value(value: Variant, declaration: Dictionary) -> bool:
	match declaration["type"]:
		"bool": return value is bool
		"int": return value is int and value >= -2147483648 and value <= 2147483647
		"enum": return value is String and value in declaration["values"]
	return false

static func _condition(item: Variant, variables: Dictionary, depth: int = 1, count: Array = [0]) -> bool:
	count[0] += 1
	if depth > 8 or count[0] > 64 or not item is Dictionary: return false
	var op: Variant = item.get("op")
	if not op is String: return false
	if op in ["all", "any"]:
		if not _fields(item, ["op", "children"]) or not _list(item["children"], 64): return false
		for child: Variant in item["children"]:
			if not _condition(child, variables, depth + 1, count): return false
		return true
	if op == "not":
		return _fields(item, ["op", "child"]) and _condition(item["child"], variables, depth + 1, count)
	if not op in ["eq", "ne", "lt", "le", "gt", "ge"] or not _fields(item, ["op", "variable", "value"]): return false
	if not _ref(item["variable"], variables): return false
	var declaration: Dictionary = variables[item["variable"]]
	return _value(item["value"], declaration) and (op in ["eq", "ne"] or declaration["type"] == "int")

static func _display(item: Dictionary, ids: Dictionary) -> bool:
	if not _id(item["text_id"]) or ids.has(item["text_id"]) or not _text(item["text"]): return false
	ids[item["text_id"]] = true
	return true

static func _story(story: Variant) -> bool:
	if not _fields(story, ["schema_version", "id", "title", "language", "entry", "characters", "variables", "nodes", "assets"]): return false
	if not story["schema_version"] is String or story["schema_version"] != "1" or not _id(story["id"]) or not _text(story["title"]): return false
	if not story["language"] is String or _languages.search(story["language"]) == null: return false
	if not _map(story["characters"], 256) or not _map(story["variables"], 256) or not _map(story["nodes"], 10000): return false
	if not story["assets"] is Dictionary or not story["assets"].is_empty(): return false
	var characters: Dictionary = story["characters"]
	var variables: Dictionary = story["variables"]
	var nodes: Dictionary = story["nodes"]
	if not _ref(story["entry"], nodes): return false
	for character: Variant in characters.values():
		if not _fields(character, ["name"]) or not _text(character["name"]): return false
	for declaration: Variant in variables.values():
		if not _fields(declaration, ["type", "initial"], ["values"]): return false
		if not declaration["type"] is String: return false
		if declaration["type"] == "enum":
			if not _list(declaration.get("values"), 256): return false
			var unique := {}
			for value: Variant in declaration["values"]:
				if not _text(value) or unique.has(value): return false
				unique[value] = true
		elif not declaration["type"] in ["bool", "int"] or declaration.has("values"): return false
		if not _value(declaration["initial"], declaration): return false
	var text_ids := {}
	var endings := {}
	for node: Variant in nodes.values():
		if not node is Dictionary: return false
		match node.get("type"):
			"line":
				if not _fields(node, ["type", "text_id", "text", "next"], ["speaker", "background", "portrait"]): return false
				if not _display(node, text_ids) or not _ref(node["next"], nodes): return false
				if node.has("speaker") and not _ref(node["speaker"], characters): return false
				if node.has("background") or node.has("portrait"): return false
			"end":
				if not _fields(node, ["type", "text_id", "text", "ending"]): return false
				if not _display(node, text_ids) or not _id(node["ending"]) or endings.has(node["ending"]): return false
				endings[node["ending"]] = true
			"choice":
				if not _fields(node, ["type", "text_id", "text", "options"]): return false
				if not _display(node, text_ids) or not _list(node["options"], 32): return false
				var option_ids := {}
				for option: Variant in node["options"]:
					if not _fields(option, ["id", "text_id", "text", "target"], ["condition"]): return false
					if not _id(option["id"]) or option_ids.has(option["id"]) or not _display(option, text_ids) or not _ref(option["target"], nodes): return false
					option_ids[option["id"]] = true
					if option.has("condition") and not _condition(option["condition"], variables, 1, [0]): return false
			"set":
				if not _fields(node, ["type", "operations", "next"]): return false
				if not _ref(node["next"], nodes) or not _list(node["operations"], 256): return false
				for operation: Variant in node["operations"]:
					if not _fields(operation, ["op", "variable", "value"]) or not _ref(operation["variable"], variables): return false
					if not operation["op"] is String: return false
					var declaration: Dictionary = variables[operation["variable"]]
					if not _value(operation["value"], declaration): return false
					if not operation["op"] in ["set", "increment"] or (operation["op"] == "increment" and declaration["type"] != "int"): return false
			"branch":
				if not _fields(node, ["type", "condition", "if_true", "if_false"]): return false
				if not _condition(node["condition"], variables, 1, [0]) or not _ref(node["if_true"], nodes) or not _ref(node["if_false"], nodes): return false
			_: return false
	return not endings.is_empty()

static func _digest(bytes: PackedByteArray) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(bytes)
	return context.finish().hex_encode()

static func validate(source: PackedByteArray, notices: PackedByteArray, package_hash: String) -> Dictionary:
	if source.size() > 5242880 or notices.size() > 1048576: return {"error": "size_limit"}
	var notice_text := notices.get_string_from_utf8()
	if notice_text.to_utf8_buffer() != notices or 0 in notices: return {"error": "invalid_notices"}
	var decoded := StrictJson.decode(source, 5242880)
	if not decoded.get("ok", false) or not _story(decoded.get("value")): return {"error": "invalid_story"}
	var manifest := '{"assets":[],"notices_sha256":"%s","schema_version":"1","story_sha256":"%s"}' % [_digest(notices), _digest(source)]
	if _digest(manifest.to_utf8_buffer()) != package_hash: return {"error": "content_hash_mismatch"}
	return {"ok": true, "story": decoded["value"]}
