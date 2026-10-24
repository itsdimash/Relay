"""Image validation and task-scoped attachment access."""
import base64
import binascii
import re
import uuid
from .contracts import IMAGE_TYPES, MAX_IMAGE_BYTES


def decode_images(value):
    if not isinstance(value, list) or len(value) > 4:
        raise ValueError('Attach up to four PNG, JPEG, or WebP images.')
    images = []
    for image in value:
        if not isinstance(image, dict) or not isinstance(image.get('name'), str) or not isinstance(image.get('data'), str):
            raise ValueError('Invalid image attachment.')
        if len(image['data']) > ((MAX_IMAGE_BYTES+2)//3)*4:
            raise ValueError('Each image must be 4 MB or smaller.')
        try: raw = base64.b64decode(image['data'], validate=True)
        except (ValueError, binascii.Error):raise ValueError('Invalid image encoding.')
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise ValueError('Each image must be between 1 byte and 4 MB.')
        mime = ('image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw)>=24 and raw[12:16]==b'IHDR' else
                'image/jpeg' if raw.startswith(b'\xff\xd8\xff') and raw.endswith(b'\xff\xd9') else
                'image/webp' if len(raw)>=16 and raw[:4]==b'RIFF' and raw[8:12]==b'WEBP' else None)
        if mime is None or image.get('mime',mime) != mime:
            raise ValueError('Use a PNG, JPEG, or WebP image. Convert HEIC files before attaching them.')
        name = image['name'].replace('\\','/').split('/')[-1].strip()[:180] or 'Image'+IMAGE_TYPES[mime]
        images.append(dict(id=uuid.uuid4().hex, name=name, mime=mime, size=len(raw), raw=raw))
    return images


def saved_image_path(app, info, image_id):
    if not isinstance(image_id,str) or not re.fullmatch(r'[0-9a-f]{32}',image_id):
        raise ValueError('Image not found.')
    folder = app.history_path(info['id'])
    image = next((item for item in info.get('attachments',[]) if item.get('id')==image_id),None)
    if not image or image.get('mime') not in IMAGE_TYPES:
        raise ValueError('Image not found.')
    path = folder/'attachments'/(image_id+IMAGE_TYPES[image['mime']])
    if folder.is_symlink() or (folder/'attachments').is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()) or not path.is_file():
        raise ValueError('Image is unavailable. Attach it again in a new task.')
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError('Saved image exceeds the attachment limit.')
    return path


def inherited_images(app, source):
    return [dict(image, raw=app.saved_image_path(source,image['id']).read_bytes()) for image in source.get('attachments',[])]
