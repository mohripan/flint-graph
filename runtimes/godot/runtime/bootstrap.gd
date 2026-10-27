# SPDX-License-Identifier: MIT
# Trusted content bootstrap and narrative player startup.
extends Control

const StrictJson = preload("res://runtime/strict_json.gd")
const GameView = preload("res://runtime/game_view.gd")


func _digest(data: PackedByteArray) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(data)
	return context.finish().hex_encode()


func _bytes(path: String, limit: int) -> PackedByteArray:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null or file.get_length() > limit:
		return PackedByteArray()
	return file.get_buffer(file.get_length())


func verify_content() -> Dictionary:
	var build: Variant = JSON.parse_string(_bytes("res://build-manifest.json", 1048576).get_string_from_utf8())
	var manifest_bytes := _bytes("res://content/package-manifest.json", 1048576)
	if not build is Dictionary or not build.get("package_hash") is String:
		return {"error": "invalid_build_manifest"}
	if _digest(manifest_bytes) != build["package_hash"]:
		return {"error": "package_hash_mismatch"}
	var manifest: Variant = JSON.parse_string(manifest_bytes.get_string_from_utf8())
	if not manifest is Dictionary or not manifest.get("assets") is Array:
		return {"error": "invalid_package_manifest"}
	var source := _bytes("res://content/story.json", 5242880)
	var notices := _bytes("res://content/NOTICES.txt", 1048576)
	if _digest(source) != manifest.get("story_sha256") or _digest(notices) != manifest.get("notices_sha256"):
		return {"error": "content_hash_mismatch"}
	var ids := RegEx.create_from_string("^[a-z][a-z0-9_-]{0,63}$")
	var assets := {}
	var total := source.size() + notices.size()
	for asset: Variant in manifest["assets"]:
		if not asset is Dictionary or not asset.get("id") is String or ids.search(asset["id"]) == null:
			return {"error": "invalid_asset_manifest"}
		if asset.get("path") != "assets/" + asset["id"] + ".png":
			return {"error": "invalid_asset_path"}
		var data := _bytes("res://content/" + asset["path"], 10485760)
		total += data.size()
		if total > 104857600:
			return {"error": "content_size_limit"}
		if _digest(data) != asset.get("sha256"):
			return {"error": "asset_hash_mismatch"}
		assets[asset["id"]] = data
	var decoded := StrictJson.decode(source, 5242880)
	if not decoded.get("ok", false) or not decoded["value"] is Dictionary:
		return {"error": "invalid_story"}
	var story: Dictionary = decoded["value"]
	if not story.get("title") is String:
		return {"error": "invalid_story"}
	return {"ok": true, "package_hash": build["package_hash"], "story": story, "assets": assets}


func _ready() -> void:
	var checked := verify_content()
	if not checked.get("ok", false):
		push_error("CONTENT_ERROR:" + checked.get("error", "invalid_content"))
		get_tree().quit(1)
		return
	print("CONTENT_OK:" + checked["package_hash"])
	if "--verify-content" in OS.get_cmdline_user_args():
		get_tree().quit(0)
		return
	var game := GameView.new()
	game.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(game)
	game.configure(checked["story"], checked["package_hash"], checked["assets"])
