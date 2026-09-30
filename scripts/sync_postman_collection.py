"""
Keeps postman/SmartGrowAI.postman_collection.json (and its environment file)
in sync with the live FastAPI route table, so a newly added endpoint never
goes missing from the importable collection.

This does NOT regenerate the collection from scratch -- the hand-written
requests (realistic example bodies, `access_token`/`tray_id` capture
scripts, friendly folder names) are far more useful than anything derived
purely from the OpenAPI schema, so they're left completely untouched. This
script only *appends* a skeleton request for any endpoint that has no
matching method+path anywhere in the collection yet, filing it into the
right folder, and adds an empty environment variable for any path
parameter it doesn't already know about.

Usage:
    python scripts/sync_postman_collection.py          # write updates in place
    python scripts/sync_postman_collection.py --check  # exit 1 if it would change anything, don't write

CI (.github/workflows/postman-sync.yml) runs this on every push that
touches app/api/v1/** or app/main.py and commits the result back, so the
collection can never silently drift behind the real API.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COLLECTION_PATH = ROOT / "postman" / "SmartGrowAI.postman_collection.json"
ENVIRONMENT_PATH = ROOT / "postman" / "SmartGrowAI.postman_environment.json"

# OpenAPI tag -> the friendlier folder name already used in the hand-curated
# collection, so newly discovered endpoints land in the existing folder
# instead of spawning a near-duplicate one. Anything not listed here falls
# back to the raw tag name as the folder name.
TAG_TO_FOLDER = {
    "Health": "Health",
    "Auth": "Auth",
    "Users": "Users (Admin)",
    "Trays": "Trays",
    "Sensor Readings": "Sensors (ESP32)",
    "Irrigation": "Irrigation",
    "Predictions": "Predictions",
    "Analytics": "Analytics (Power BI)",
    "AI Agent": "AI Agent",
}

# Header parameters that map to a specific, already-documented environment
# variable rather than a generic guess.
HEADER_ENV_VAR = {
    "x-device-key": "device_key",
}

PLACEHOLDER_BY_TYPE: dict[str, Any] = {
    "string": "",
    "integer": 0,
    "number": 0,
    "boolean": False,
    "array": [],
    "object": {},
}


def load_openapi_spec() -> dict[str, Any]:
    # Imported lazily: importing app.main only needs settings defaults, no
    # live Mongo connection (that happens in the lifespan, not at import
    # time), but it does need the project's deps installed.
    from app.main import app

    return app.openapi()


def resolve_example(schema: dict[str, Any], components: dict[str, Any]) -> Any:
    """Best-effort placeholder value for a (possibly $ref'd) JSON schema."""
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        schema = components.get("schemas", {}).get(name, {})
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            if option.get("type") != "null":
                return resolve_example(option, components)
        return None
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        return {key: resolve_example(prop, components) for key, prop in schema.get("properties", {}).items()}
    if schema_type == "array":
        items = schema.get("items", {})
        return [resolve_example(items, components)] if items else []
    return PLACEHOLDER_BY_TYPE.get(schema_type, "")


def postman_segments_to_openapi_path(path_segments: list[str]) -> str:
    """Turn Postman's ["api","v1","trays","{{tray_id}}"] into "/api/v1/trays/{tray_id}"."""
    parts = []
    for segment in path_segments:
        match = re.fullmatch(r"\{\{(\w+)\}\}", segment)
        parts.append("{" + match.group(1) + "}" if match else segment)
    return "/" + "/".join(parts)


def collect_existing_operations(collection: dict[str, Any]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()

    def walk(items: list[dict[str, Any]]) -> None:
        for entry in items:
            if "item" in entry:
                walk(entry["item"])
                continue
            request = entry.get("request")
            if not request:
                continue
            path_segments = request.get("url", {}).get("path", [])
            if not path_segments:
                continue
            method = request.get("method", "GET").upper()
            found.add((method, postman_segments_to_openapi_path(path_segments)))

    walk(collection.get("item", []))
    return found


def build_request_item(method: str, path: str, operation: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    path_params = [p for p in operation.get("parameters", []) if p.get("in") == "path"]
    query_params = [p for p in operation.get("parameters", []) if p.get("in") == "query"]
    header_params = [p for p in operation.get("parameters", []) if p.get("in") == "header"]

    segments = [s for s in path.strip("/").split("/") if s]
    postman_segments = [f"{{{{{s[1:-1]}}}}}" if s.startswith("{") and s.endswith("}") else s for s in segments]

    headers: list[dict[str, str]] = []
    if operation.get("security"):
        headers.append({"key": "Authorization", "value": "Bearer {{access_token}}"})
    for param in header_params:
        name = param["name"]
        env_var = HEADER_ENV_VAR.get(name.lower(), re.sub(r"[^0-9a-zA-Z]+", "_", name.lower()).strip("_"))
        headers.append({"key": name, "value": f"{{{{{env_var}}}}}"})

    request: dict[str, Any] = {"method": method, "header": headers}

    request_body = operation.get("requestBody")
    if request_body:
        json_schema = request_body.get("content", {}).get("application/json", {}).get("schema")
        if json_schema is not None:
            example = resolve_example(json_schema, components)
            headers.insert(0, {"key": "Content-Type", "value": "application/json"})
            request["body"] = {"mode": "raw", "raw": json.dumps(example, indent=2)}

    query = []
    for param in query_params:
        default = param.get("schema", {}).get("default", "")
        query.append({"key": param["name"], "value": str(default)})

    raw_path = "/".join(postman_segments)
    raw_url = "{{base_url}}/" + raw_path
    if query:
        raw_url += "?" + "&".join(f"{q['key']}={q['value']}" for q in query)

    url: dict[str, Any] = {"raw": raw_url, "host": ["{{base_url}}"], "path": postman_segments}
    if query:
        url["query"] = query
    request["url"] = url

    item: dict[str, Any] = {"name": operation.get("summary") or f"{method} {path}", "request": request}
    if operation.get("description"):
        item["description"] = (
            "Auto-added by scripts/sync_postman_collection.py -- flesh out the example body/tests by hand. "
            + operation["description"]
        )
    else:
        item["description"] = "Auto-added by scripts/sync_postman_collection.py -- flesh out the example body/tests by hand."

    return item, [p["name"] for p in path_params]


def find_or_create_folder(collection: dict[str, Any], name: str) -> dict[str, Any]:
    for entry in collection.setdefault("item", []):
        if entry.get("name") == name and "item" in entry:
            return entry
    folder = {"name": name, "item": []}
    collection["item"].append(folder)
    return folder


def sync(check_only: bool) -> bool:
    collection = json.loads(COLLECTION_PATH.read_text(encoding="utf-8"))
    environment = json.loads(ENVIRONMENT_PATH.read_text(encoding="utf-8"))

    existing_ops = collect_existing_operations(collection)
    known_env_vars = {v["key"] for v in environment.get("values", [])}

    spec = load_openapi_spec()
    components = spec.get("components", {})

    changed = False
    new_path_params: list[str] = []

    for path, methods in spec.get("paths", {}).items():
        for method, operation in methods.items():
            method = method.upper()
            if (method, path) in existing_ops:
                continue

            tag = (operation.get("tags") or ["Uncategorized"])[0]
            folder_name = TAG_TO_FOLDER.get(tag, tag)
            folder = find_or_create_folder(collection, folder_name)

            item, path_param_names = build_request_item(method, path, operation, components)
            folder["item"].append(item)
            new_path_params.extend(path_param_names)
            changed = True

    for name in new_path_params:
        if name not in known_env_vars:
            environment.setdefault("values", []).append({"key": name, "value": "", "enabled": True})
            known_env_vars.add(name)
            changed = True

    if changed and not check_only:
        COLLECTION_PATH.write_text(json.dumps(collection, indent=2) + "\n", encoding="utf-8")
        ENVIRONMENT_PATH.write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")

    return changed


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    changed = sync(check_only)

    if changed:
        if check_only:
            print("postman collection/environment are missing endpoints -- run scripts/sync_postman_collection.py")
            return 1
        print("Updated postman/SmartGrowAI.postman_collection.json (and environment) with newly discovered endpoints.")
        return 0

    print("postman collection is already in sync with the API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
