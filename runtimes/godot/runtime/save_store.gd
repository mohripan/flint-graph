# SPDX-License-Identifier: MIT
# Publish a verified sibling candidate; never truncate the last good save first.
extends RefCounted

const SAVE_LIMIT := 6291456

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
