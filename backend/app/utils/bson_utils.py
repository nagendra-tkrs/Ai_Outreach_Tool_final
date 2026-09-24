from datetime import datetime
from bson import ObjectId

def is_valid_object_id(id_val):
    if not id_val:
        return False
    return ObjectId.is_valid(str(id_val))

def to_object_id(id_val):
    if not id_val:
        return None
    if isinstance(id_val, ObjectId):
        return id_val
    try:
        return ObjectId(str(id_val))
    except Exception:
        return None


def serialize_doc(doc):
    """
    Recursively converts MongoDB document types (ObjectId, datetime)
    to JSON-friendly formats, converting `_id` to string `_id` and/or `id`.
    """
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(item) for item in doc]
    if isinstance(doc, dict):
        result = {}
        for key, value in doc.items():
            if isinstance(value, ObjectId):
                result[key] = str(value)
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, dict):
                result[key] = serialize_doc(value)
            elif isinstance(value, list):
                result[key] = [serialize_doc(item) for item in value]
            else:
                result[key] = value
        return result
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    return doc
