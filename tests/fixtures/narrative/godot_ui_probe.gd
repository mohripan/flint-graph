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
