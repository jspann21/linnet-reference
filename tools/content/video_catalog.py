import struct

CATALOG_HEADER_SIZE = 12
CATALOG_ROW_SIZE = 416
CATALOG_MAX_BYTES = CATALOG_HEADER_SIZE + 256 * CATALOG_ROW_SIZE


def encode(entries):
    data = struct.pack('<4sII', b'LVIX', len(entries), CATALOG_ROW_SIZE)
    for key, path, title in entries:
        raw_path = path.encode('ascii')
        raw_title = title.encode('utf-8')
        if not raw_path.startswith(b'/') or len(raw_path) > 255 or len(raw_title) > 127:
            raise ValueError('video catalog path or title exceeds firmware bounds')
        data += key + raw_path.ljust(256, b'\0') + raw_title.ljust(128, b'\0')
    return data


def decode(data):
    """Validate the bounded firmware catalog before preserving existing entries."""
    if len(data)<CATALOG_HEADER_SIZE:
        raise ValueError('invalid video catalog header')
    magic,count,size=struct.unpack_from('<4sII', data)
    if magic!=b'LVIX' or count>256 or size!=CATALOG_ROW_SIZE or len(data)!=CATALOG_HEADER_SIZE+count*size:
        raise ValueError('invalid video catalog layout')
    entries=[]
    names=set()
    keys=set()
    for at in range(CATALOG_HEADER_SIZE,len(data),size):
        key=data[at:at+32]
        raw_name=data[at+32:at+288]
        raw_title=data[at+288:at+size]
        path=raw_name.split(b'\0',1)[0].decode('ascii')
        title=raw_title.split(b'\0',1)[0].decode('utf-8')
        valid_name = path.startswith('/') and all((i == 1 and part.upper() == '.LINNET') or
            (part and len(part.split('.')[0])<=8 and ('.' not in part or len(part.rsplit('.',1)[1])<=3))
            for i,part in enumerate(path.split('/')[1:],1))
        if not valid_name or path.casefold() in names or key in keys or not title or b'\0' not in raw_title or b'\0' not in raw_name:
            raise ValueError('invalid video catalog entry')
        names.add(path.casefold()); keys.add(key)
        entries.append((key,path,title))
    return entries


def read_file(path):
    with path.open("rb") as reader:
        data = reader.read(CATALOG_MAX_BYTES + 1)
    if len(data) > CATALOG_MAX_BYTES:
        raise ValueError("Video catalog exceeds supported size")
    return data, decode(data)
