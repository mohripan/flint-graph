# SPDX-License-Identifier: MIT
# Strict bounded JSON for the v1 story/save subset. Godot's general JSON parser
# permits trailing commas and float coercion; these boundaries deliberately do not.
extends RefCounted

var _source := ""
var _position := 0
var _bad := false


static func decode(data: PackedByteArray, limit: int) -> Dictionary:
	if data.size() > limit:
		return {"ok": false}
	var reader := new()
	reader._source = data.get_string_from_utf8()
	if reader._source.to_utf8_buffer() != data:
		return {"ok": false}
	var value: Variant = reader._value(0)
	reader._space()
	if reader._bad or reader._position != reader._source.length():
		return {"ok": false}
	return {"ok": true, "value": value}


func _peek() -> String:
	return _source[_position] if _position < _source.length() else ""


func _space() -> void:
	while _position < _source.length() and _peek() in [" ", "\t", "\n", "\r"]:
		_position += 1


func _value(depth: int) -> Variant:
	_space()
	var char := _peek()
	if char == '"':
		return _string()
	if char in ["{", "["]:
		if depth >= 64:
			_bad = true
			return null
		return _object(depth) if char == "{" else _array(depth)
	for literal: String in ["true", "false", "null"]:
		if _source.substr(_position, literal.length()) == literal:
			_position += literal.length()
			return true if literal == "true" else (false if literal == "false" else null)
	return _number()


func _object(depth: int) -> Dictionary:
	var result := {}
	_position += 1
	_space()
	if _peek() == "}":
		_position += 1
		return result
	while not _bad:
		if _peek() != '"':
			_bad = true
			break
		var key := _string()
		_space()
		if _bad or _peek() != ":" or result.has(key):
			_bad = true
			break
		_position += 1
		result[key] = _value(depth + 1)
		_space()
		if _peek() == "}":
			_position += 1
			return result
		if _peek() != ",":
			_bad = true
			break
		_position += 1
		_space()
	return result


func _array(depth: int) -> Array:
	var result: Array = []
	_position += 1
	_space()
	if _peek() == "]":
		_position += 1
		return result
	while not _bad:
		result.append(_value(depth + 1))
		_space()
		if _peek() == "]":
			_position += 1
			return result
		if _peek() != ",":
			_bad = true
			break
		_position += 1
	return result


func _hex4(start: int) -> int:
	if start + 4 > _source.length():
		_bad = true
		return -1
	var result := 0
	for offset in range(4):
		var digit := "0123456789abcdef".find(_source[start + offset].to_lower())
		if digit < 0:
			_bad = true
			return -1
		result = result * 16 + digit
	return result


func _string() -> String:
	var start := _position
	_position += 1
	while _position < _source.length() and not _bad:
		var char := _peek()
		if char == '"':
			_position += 1
			var parsed: Variant = JSON.parse_string(_source.substr(start, _position - start))
			if parsed is String:
				return parsed
			_bad = true
			break
		if char.unicode_at(0) < 32:
			_bad = true
			break
		if char != "\\":
			_position += 1
			continue
		_position += 1
		var escaped := _peek()
		if escaped == "u":
			var code := _hex4(_position + 1)
			_position += 5
			if code == 0 or (code >= 0xdc00 and code <= 0xdfff):
				_bad = true
			elif code >= 0xd800 and code <= 0xdbff:
				if _source.substr(_position, 2) != "\\u":
					_bad = true
				else:
					var low := _hex4(_position + 2)
					if low < 0xdc00 or low > 0xdfff:
						_bad = true
					_position += 6
		elif escaped in ['"', "\\", "/", "b", "f", "n", "r", "t"]:
			_position += 1
		else:
			_bad = true
	_bad = true
	return ""


func _digit(char: String) -> bool:
	return char.length() == 1 and char.unicode_at(0) >= 48 and char.unicode_at(0) <= 57


func _number() -> Variant:
	var start := _position
	if _peek() == "-":
		_position += 1
	if not _digit(_peek()):
		_bad = true
		return null
	if _peek() == "0":
		_position += 1
	else:
		while _digit(_peek()):
			_position += 1
	if _peek() in [".", "e", "E"] or _position - start > 11:
		_bad = true
		return null
	var value := _source.substr(start, _position - start).to_int()
	if value < -2147483648 or value > 2147483647:
		_bad = true
		return null
	return value
