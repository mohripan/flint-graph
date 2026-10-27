# Trusted packaging regression harness; run outside the exported source tree.
extends SceneTree


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 1 or not ProjectSettings.load_resource_pack(args[0]):
		quit(1)
		return
	var results := {}
	for path: String in ["fonts/LICENSE-Lora.txt", "fonts/provenance.json", "content/story.json",
			"content/NOTICES.txt", "LICENSE.runtime.txt", "GODOT-NOTICE.txt"]:
		var context := HashingContext.new()
		context.start(HashingContext.HASH_SHA256)
		context.update(FileAccess.get_file_as_bytes("res://" + path))
		results[path] = context.finish().hex_encode()
	print("PACK_RESULT:" + JSON.stringify(results))
	quit(0)
