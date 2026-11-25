"""校验本目录里用到的 JSON Schema 子集：type、const、enum、required、additionalProperties、items。"""


def _matches(instance, type_name):
    if type_name == "object":
        return isinstance(instance, dict)
    if type_name == "array":
        return isinstance(instance, list)
    if type_name == "string":
        return isinstance(instance, str)
    if type_name == "boolean":
        return isinstance(instance, bool)
    if type_name == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if type_name == "null":
        return instance is None
    return False


def check(instance, schema, path="$"):
    errors = []
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path} 不是规定常量")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path} 不在枚举内: {instance!r}")
    types = schema.get("type")
    if types:
        names = types if isinstance(types, list) else [types]
        if not any(_matches(instance, name) for name in names):
            errors.append(f"{path} 类型不符")
            return errors
        active = None
        for name in names:
            if _matches(instance, name):
                active = name
                break
    else:
        active = "object" if isinstance(instance, dict) else None
    if active == "object":
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}.{key} 缺失")
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append(f"{path}.{key} 不在契约内")
        for key, value in instance.items():
            if key in props:
                errors.extend(check(value, props[key], f"{path}.{key}"))
    if active == "array" and "items" in schema:
        for index, value in enumerate(instance):
            errors.extend(check(value, schema["items"], f"{path}[{index}]"))
    return errors
