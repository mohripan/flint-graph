extends SceneTree

func _initialize() -> void:
	var validator: GDScript = load("res://validate_story.gd")
	var cases: Array = JSON.parse_string(FileAccess.get_file_as_string("res://cases.json"))
	var results := []
	for item: Dictionary in cases:
		var checked: Dictionary = validator.validate(Marshalls.base64_to_raw(item["source"]), Marshalls.base64_to_raw(item["notices"]), item["hash"])
		results.append(checked.get("ok", false))
	print("PREVIEW_PROBE:" + JSON.stringify(results))
	quit(0)
