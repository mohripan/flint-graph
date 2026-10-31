# SPDX-License-Identifier: MIT
# Dynamic previews have the same bounded v1 and v2 semantics as the Python loader.
# v2 (ADR 0040) adds typed assets, sprites, a closed theme, stage nodes and expressions;
# ADR 0043 adds audio assets and line voices;
# asset bytes arrive separately and must match the story's hashes exactly.
extends RefCounted
const StrictJson = preload("res://runtime/strict_json.gd")
const POSITIONS := ["left", "center", "right"]
const RESERVED := ["con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5", "com6",
	"com7", "com8", "com9", "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9"]
static var _ids := RegEx.create_from_string("^[a-z][a-z0-9_-]{0,63}\\z")
static var _languages := RegEx.create_from_string("^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*\\z")
static var _hashes := RegEx.create_from_string("^[0-9a-f]{64}\\z")
static var _colors := RegEx.create_from_string("^#[0-9a-f]{6}([0-9a-f]{2})?\\z")

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

static func _asset(value: Variant, assets: Dictionary, kind: String) -> bool:
	return _ref(value, assets) and assets[value]["kind"] == kind

static func _color(value: Variant, regex: RegEx) -> bool:
	return value is String and regex.search(value) != null

static func _within(value: Variant, low: int, high: int) -> bool:
	return value is int and value >= low and value <= high

static func _assets_v2(assets: Variant) -> bool:
	if not _map(assets, 256): return false
	for key: String in assets:
		var asset: Variant = assets[key]
		if key in RESERVED or not _fields(asset, ["kind", "path", "sha256"]): return false
		if not asset["path"] is String or not asset["sha256"] is String or _hashes.search(asset["sha256"]) == null: return false
		match asset["kind"]:
			"image":
				if asset["path"] != "assets/" + key + ".png": return false
			"font":
				if not asset["path"] in ["assets/" + key + ".ttf", "assets/" + key + ".otf"]: return false
			"audio":
				if asset["path"] != "assets/" + key + ".wav": return false
			_: return false
	return true

# A spoken line or a short vocalization (ADR 0043); without audio it stays silent.
static func _voice(node: Dictionary, assets: Dictionary) -> bool:
	var voice: Variant = node["voice"]
	if not _fields(voice, ["mode"], ["text", "audio"]): return false
	if not voice["mode"] in ["full", "vocalization"] or not node.has("speaker"): return false
	if (voice["mode"] == "vocalization") != voice.has("text"): return false
	if voice.has("text") and (not _text(voice["text"]) or voice["text"].length() > 40): return false
	return not voice.has("audio") or _asset(voice["audio"], assets, "audio")

static func _theme(theme: Variant, assets: Dictionary) -> bool:
	if not _fields(theme, [], ["textbox", "name", "choices", "font"]): return false
	if theme.has("textbox"):
		var box: Variant = theme["textbox"]
		if not _fields(box, [], ["position", "width", "background", "text", "border", "radius"]): return false
		if box.has("position") and not box["position"] in ["bottom", "middle", "top"]: return false
		if box.has("width") and not _within(box["width"], 40, 100): return false
		if box.has("radius") and not _within(box["radius"], 0, 48): return false
		for part: String in ["background", "text", "border"]:
			if box.has(part) and not _color(box[part], _colors): return false
	if theme.has("name"):
		var named: Variant = theme["name"]
		if not _fields(named, [], ["show", "background", "text"]): return false
		if named.has("show") and not named["show"] is bool: return false
		for part: String in ["background", "text"]:
			if named.has(part) and not _color(named[part], _colors): return false
	if theme.has("choices"):
		var choices: Variant = theme["choices"]
		if not _fields(choices, [], ["background", "text", "border"]): return false
		for part: String in choices:
			if not _color(choices[part], _colors): return false
	if theme.has("font"):
		var font: Variant = theme["font"]
		if not _fields(font, [], ["asset", "size"]): return false
		if font.get("asset") != null and not _asset(font["asset"], assets, "font"): return false
		if font.has("size") and not _within(font["size"], 14, 48): return false
	return true

static func _stage(node: Dictionary, characters: Dictionary, assets: Dictionary, nodes: Dictionary) -> bool:
	if not _fields(node, ["type", "next"], ["background", "cg", "show", "hide"]): return false
	if not node.has("background") and not node.has("cg") and not node.has("show") and not node.has("hide"): return false
	if node.has("cg") and node["cg"] != null and not _asset(node["cg"], assets, "image"): return false
	if node.has("background") and node["background"] != null and not _asset(node["background"], assets, "image"): return false
	var hidden := {}
	if node.has("hide"):
		if not _list(node["hide"], 8): return false
		for character: Variant in node["hide"]:
			if not _ref(character, characters) or hidden.has(character): return false
			hidden[character] = true
	if node.has("show"):
		if not _list(node["show"], 8): return false
		var shown := {}
		var taken := {}
		for entry: Variant in node["show"]:
			if not _fields(entry, ["character", "sprite", "position"], ["x"]) or not _ref(entry["character"], characters): return false
			if entry.has("x") and not _within(entry["x"], 0, 100): return false
			if not _ref(entry["sprite"], characters[entry["character"]].get("sprites", {})): return false
			if not entry["position"] is String or not entry["position"] in POSITIONS: return false
			if shown.has(entry["character"]) or hidden.has(entry["character"]) or taken.has(entry["position"]): return false
			shown[entry["character"]] = true
			taken[entry["position"]] = true
	return _ref(node["next"], nodes)

static func _story(story: Variant) -> bool:
	var v2: bool = story is Dictionary and story.get("schema_version") is String and story["schema_version"] == "2"
	if not _fields(story, ["schema_version", "id", "title", "language", "entry", "characters", "variables", "nodes", "assets"], ["theme"] if v2 else []): return false
	if not story["schema_version"] is String or not story["schema_version"] in ["1", "2"] or not _id(story["id"]) or not _text(story["title"]): return false
	if not story["language"] is String or _languages.search(story["language"]) == null: return false
	if not _map(story["characters"], 256) or not _map(story["variables"], 256) or not _map(story["nodes"], 10000): return false
	if v2:
		if not _assets_v2(story["assets"]): return false
	elif not story["assets"] is Dictionary or not story["assets"].is_empty(): return false
	var assets: Dictionary = story["assets"]
	var characters: Dictionary = story["characters"]
	var variables: Dictionary = story["variables"]
	var nodes: Dictionary = story["nodes"]
	if not _ref(story["entry"], nodes): return false
	for character: Variant in characters.values():
		if not _fields(character, ["name"], ["color", "sprites", "stage"] if v2 else []) or not _text(character["name"]): return false
		if character.has("stage"):
			var framing: Variant = character["stage"]
			if not _fields(framing, [], ["scale", "top"]): return false
			if framing.has("scale") and not _within(framing["scale"], 40, 300): return false
			if framing.has("top") and not _within(framing["top"], -50, 100): return false
		if character.has("color") and not _color(character["color"], _colors): return false
		if character.has("sprites"):
			if not _map(character["sprites"], 32): return false
			for sprite: Variant in character["sprites"].values():
				if not _asset(sprite, assets, "image"): return false
	if story.has("theme") and not _theme(story["theme"], assets): return false
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
				if not _fields(node, ["type", "text_id", "text", "next"], ["speaker", "expression", "voice"] if v2 else ["speaker", "background", "portrait"]): return false
				if not _display(node, text_ids) or not _ref(node["next"], nodes): return false
				if node.has("speaker") and not _ref(node["speaker"], characters): return false
				if node.has("background") or node.has("portrait"): return false
				if node.has("expression") and (not node.has("speaker") or not _ref(node["expression"], characters[node["speaker"]].get("sprites", {}))): return false
				if node.has("voice") and not _voice(node, assets): return false
			"stage":
				if not v2 or not _stage(node, characters, assets, nodes): return false
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

static func validate(source: PackedByteArray, notices: PackedByteArray, package_hash: String, assets: Dictionary = {}) -> Dictionary:
	if source.size() > 5242880 or notices.size() > 1048576: return {"error": "size_limit"}
	var notice_text := notices.get_string_from_utf8()
	if notice_text.to_utf8_buffer() != notices or 0 in notices: return {"error": "invalid_notices"}
	var decoded := StrictJson.decode(source, 5242880)
	if not decoded.get("ok", false) or not _story(decoded.get("value")): return {"error": "invalid_story"}
	# The package identity covers every asset: exactly the declared files, by SHA-256.
	var declared: Dictionary = decoded["value"]["assets"]
	if declared.size() != assets.size(): return {"error": "asset_mismatch"}
	var keys: Array = declared.keys()
	keys.sort()
	var entries: PackedStringArray = []
	var total := source.size() + notices.size()
	for key: String in keys:
		if not assets.has(key) or not assets[key] is PackedByteArray: return {"error": "asset_mismatch"}
		var data: PackedByteArray = assets[key]
		total += data.size()
		if data.size() > (8388608 if declared[key]["kind"] == "font" else 10485760) or total > 104857600: return {"error": "size_limit"}
		if _digest(data) != declared[key]["sha256"]: return {"error": "asset_hash_mismatch"}
		entries.append('{"id":"%s","path":"%s","sha256":"%s"}' % [key, declared[key]["path"], declared[key]["sha256"]])
	var manifest := '{"assets":[%s],"notices_sha256":"%s","schema_version":"1","story_sha256":"%s"}' % [",".join(entries), _digest(notices), _digest(source)]
	if _digest(manifest.to_utf8_buffer()) != package_hash: return {"error": "content_hash_mismatch"}
	return {"ok": true, "story": decoded["value"]}
