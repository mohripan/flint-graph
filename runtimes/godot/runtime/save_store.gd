# SPDX-License-Identifier: MIT
# Publish a verified sibling candidate; never truncate the last good save first.
extends RefCounted

const Reading = preload("res://runtime/reading.gd")
const SAVE_LIMIT := 6291456
const READ_MARKS_LIMIT := 2097152

class LocalIO:
	extends RefCounted
	func prepare(path: String) -> Error:
		return DirAccess.make_dir_recursive_absolute(path)
	func write(path: String, data: PackedByteArray) -> Error:
		if FileAccess.file_exists(path) or DirAccess.dir_exists_absolute(path):
			return ERR_ALREADY_EXISTS
		var file := FileAccess.open(path, FileAccess.WRITE)
		if file == null:
			return ERR_FILE_CANT_WRITE
		file.store_buffer(data)
		file.flush()
		var error := file.get_error()
		file.close()
		return error
	func read(path: String, limit: int) -> Dictionary:
		if not FileAccess.file_exists(path):
			return {"error": "not_found"}
		var file := FileAccess.open(path, FileAccess.READ)
		if file == null:
			return {"error": "save_read_failed"}
		if file.get_length() > limit:
			file.close()
			return {"error": "save_too_large"}
		var data := file.get_buffer(file.get_length())
		var error := file.get_error()
		file.close()
		return {"error": "", "data": data} if error == OK else {"error": "save_read_failed"}
	func replace(source: String, target: String) -> Error:
		return DirAccess.rename_absolute(source, target)


static func path_for(content_hash: String) -> String:
	if RegEx.create_from_string("^[0-9a-f]{64}$").search(content_hash) == null:
		return ""
	return "user://flint_graph/" + content_hash + "/game.json"


static func read_save(content_hash: String) -> Dictionary:
	var path := path_for(content_hash)
	if path == "":
		return {"error": "invalid_save_path"}
	return LocalIO.new().read(path, SAVE_LIMIT)


static func write_save(content_hash: String, data: PackedByteArray, storage: RefCounted = null) -> String:
	var path := path_for(content_hash)
	return _write_verified(path, data, SAVE_LIMIT, storage)


# Quick save (ADR 0064) is a second slot in the same format as the regular one.
static func quick_path_for(content_hash: String) -> String:
	var path := path_for(content_hash)
	return "" if path == "" else path.get_base_dir() + "/quick.json"


static func read_quick_save(content_hash: String) -> Dictionary:
	var path := quick_path_for(content_hash)
	if path == "":
		return {"error": "invalid_save_path"}
	return LocalIO.new().read(path, SAVE_LIMIT)


static func write_quick_save(content_hash: String, data: PackedByteArray) -> String:
	return _write_verified(quick_path_for(content_hash), data, SAVE_LIMIT)


# Which lines this device has read, per story, so Skip can stop at new text (ADR 0064).
static func read_marks_path(story_id: String) -> String:
	if RegEx.create_from_string("^[a-z][a-z0-9_-]{0,63}$").search(story_id) == null:
		return ""
	return "user://flint_graph/read-" + story_id + ".json"


static func read_marks(story_id: String) -> Dictionary:
	var path := read_marks_path(story_id)
	if path == "":
		return {}
	var saved := LocalIO.new().read(path, READ_MARKS_LIMIT)
	if saved.get("error", "") != "":
		return {}
	var decoded: Dictionary = preload("res://runtime/strict_json.gd").decode(saved["data"], READ_MARKS_LIMIT)
	if not decoded.get("ok", false) or not decoded["value"] is Dictionary:
		return {}
	var value: Dictionary = decoded["value"]
	if value.size() != 2 or value.get("schema_version") != "1" or not value.get("read") is Array:
		return {}
	var marks := {}
	for mark: Variant in value["read"]:
		if not mark is String or marks.size() >= Reading.MAX_READ_MARKS:
			return {}
		marks[mark] = true
	return marks


static func write_read_marks(story_id: String, marks: Array) -> String:
	if marks.size() > Reading.MAX_READ_MARKS:
		return "invalid_save"
	var data := JSON.stringify({"schema_version": "1", "read": marks}).to_utf8_buffer()
	return _write_verified(read_marks_path(story_id), data, READ_MARKS_LIMIT)


static func gallery_path(story_id: String) -> String:
	if RegEx.create_from_string("^[a-z][a-z0-9_-]{0,63}$").search(story_id) == null:
		return ""
	return "user://flint_graph/gallery-" + story_id + ".json"


static func read_gallery(story_id: String) -> Array:
	var path := gallery_path(story_id)
	if path == "":
		return []
	var saved := LocalIO.new().read(path, 32768)
	if saved.get("error", "") != "":
		return []
	var decoded: Dictionary = preload("res://runtime/strict_json.gd").decode(saved["data"], 32768)
	if not decoded.get("ok", false) or not decoded["value"] is Dictionary:
		return []
	var value: Dictionary = decoded["value"]
	if value.size() != 2 or value.get("schema_version") != "1" or not value.get("seen") is Array or value["seen"].size() > 256:
		return []
	for id: Variant in value["seen"]:
		if not id is String:
			return []
	return value["seen"]


static func write_gallery(story_id: String, seen: Array) -> String:
	if seen.size() > 256:
		return "invalid_save"
	var data := JSON.stringify({"schema_version": "1", "seen": seen}).to_utf8_buffer()
	return _write_verified(gallery_path(story_id), data, 32768)


# Player terms accepted on this device (ADR 0045): the SHA-256 of the terms text, so
# changed terms ask again. Kept per story outside save slots, like gallery unlocks.
static func terms_path(story_id: String) -> String:
	if RegEx.create_from_string("^[a-z][a-z0-9_-]{0,63}$").search(story_id) == null:
		return ""
	return "user://flint_graph/terms-" + story_id + ".json"


static func read_terms(story_id: String) -> String:
	var path := terms_path(story_id)
	if path == "":
		return ""
	var saved := LocalIO.new().read(path, 4096)
	if saved.get("error", "") != "":
		return ""
	var decoded: Dictionary = preload("res://runtime/strict_json.gd").decode(saved["data"], 4096)
	if not decoded.get("ok", false) or not decoded["value"] is Dictionary:
		return ""
	var value: Dictionary = decoded["value"]
	var digest: Variant = value.get("accepted_sha256")
	if value.size() != 2 or value.get("schema_version") != "1" or not digest is String:
		return ""
	if RegEx.create_from_string("^[0-9a-f]{64}$").search(digest) == null:
		return ""
	return digest


static func write_terms(story_id: String, digest: String) -> String:
	var data := JSON.stringify({"schema_version": "1", "accepted_sha256": digest}).to_utf8_buffer()
	return _write_verified(terms_path(story_id), data, 4096)


# Player settings on this device (ADR 0043, ADR 0064). Files from runtime 0.7.0 and older
# hold only the voice volume, as schema 1; anything malformed falls back to the defaults.
const SETTINGS_PATH := "user://flint_graph/settings.json"


static func default_settings() -> Dictionary:
	return {"voice_volume": 100, "text_speed": Reading.DEFAULT_TEXT_SPEED,
		"auto_speed": Reading.DEFAULT_AUTO_SPEED, "speaker_focus": true, "reduced_motion": false,
		"music_volume": 80, "ambience_volume": 80, "effects_volume": 100, "muted": false}


static func settings_saved() -> bool:
	return FileAccess.file_exists(SETTINGS_PATH)


static func read_settings() -> Dictionary:
	var settings := default_settings()
	var saved := LocalIO.new().read(SETTINGS_PATH, 4096)
	if saved.get("error", "") != "":
		return settings
	var decoded: Dictionary = preload("res://runtime/strict_json.gd").decode(saved["data"], 4096)
	if not decoded.get("ok", false) or not decoded["value"] is Dictionary:
		return settings
	var value: Dictionary = decoded["value"]
	var volume: Variant = value.get("voice_volume")
	if not volume is int or volume < 0 or volume > 100:
		return settings
	if value.get("schema_version") == "1" and value.size() == 2:
		settings["voice_volume"] = volume
	elif value.get("schema_version") == "2":
		if not value.get("text_speed") in Reading.TEXT_SPEEDS or not value.get("auto_speed") in Reading.AUTO_SPEEDS:
			return settings
		var read := settings.duplicate()
		for key: String in value:
			if key != "schema_version" and not read.has(key):
				return settings
			if key in ["speaker_focus", "reduced_motion", "muted"] and not value[key] is bool:
				return settings
			if key.ends_with("_volume") and (not value[key] is int or value[key] < 0 or value[key] > 100):
				return settings
			if key != "schema_version":
				read[key] = value[key]  # Files from older players lack the newer settings.
		if not value.get("speaker_focus") is bool:
			return settings
		settings = read
	return settings


static func write_settings(settings: Dictionary) -> String:
	var volume: Variant = settings.get("voice_volume")
	if not volume is int or volume < 0 or volume > 100:
		return "invalid_save"
	var data := JSON.stringify(settings.merged({"schema_version": "2"})).to_utf8_buffer()
	return _write_verified(SETTINGS_PATH, data, 4096)


static func read_voice_volume() -> int:
	return read_settings()["voice_volume"]


static func _write_verified(path: String, data: PackedByteArray, limit: int, storage: RefCounted = null) -> String:
	if path == "":
		return "invalid_save_path"
	if data.is_empty() or data.size() > limit:
		return "invalid_save"
	var io := storage if storage != null else LocalIO.new()
	var random := Crypto.new().generate_random_bytes(16)
	if random.size() != 16 or io.prepare(path.get_base_dir()) != OK:
		return "save_write_failed"
	var candidate := path.get_base_dir() + "/.pending-" + random.hex_encode() + ".json"
	if io.write(candidate, data) != OK:
		return "save_write_failed"
	var verified: Dictionary = io.read(candidate, limit)
	if verified.get("error", "save_verify_failed") != "" or verified.get("data") != data:
		return "save_verify_failed"
	if io.replace(candidate, path) != OK:
		return "save_replace_failed"
	# Failed candidates remain inspectable; no deletion or automatic retry of old files.
	return ""
