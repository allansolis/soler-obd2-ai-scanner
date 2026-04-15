"""Extrae cookies de TODOS los perfiles Chrome + Edge para systeme.io/vimeo."""
import os, sys, json, base64, sqlite3, shutil
from pathlib import Path
import win32crypt
from Crypto.Cipher import AES

DOMAINS = ['systeme.io', 'autotech', 'hptuners', 'vimeo']
BROWSERS = [
    ('Chrome', Path(os.path.expanduser('~/AppData/Local/Google/Chrome/User Data'))),
    ('Edge', Path(os.path.expanduser('~/AppData/Local/Microsoft/Edge/User Data'))),
]
OUTPUT = Path('D:/Herramientas/SOLER/cookies.txt')


def get_key(user_data):
    ls = user_data / 'Local State'
    if not ls.exists(): return None
    with open(ls, 'r', encoding='utf-8') as f:
        state = json.load(f)
    try:
        enc = base64.b64decode(state['os_crypt']['encrypted_key'])[5:]
        return win32crypt.CryptUnprotectData(enc, None, None, None, 0)[1]
    except Exception:
        return None


def decrypt(enc, key):
    try:
        if enc[:3] in (b'v10', b'v11'):
            nonce = enc[3:15]
            ct = enc[15:-16]
            tag = enc[-16:]
            return AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(ct, tag).decode('utf-8', errors='replace')
        else:
            return win32crypt.CryptUnprotectData(enc, None, None, None, 0)[1].decode('utf-8', errors='replace')
    except Exception:
        return ''


def extract(browser_name, user_data):
    key = get_key(user_data)
    if not key: return []
    results = []
    for profile_dir in user_data.iterdir():
        if not profile_dir.is_dir(): continue
        # Find Cookies file
        for candidate in [profile_dir / 'Network' / 'Cookies', profile_dir / 'Cookies']:
            if candidate.exists():
                break
        else:
            continue
        try:
            tmp = Path('C:/Users/andre/AppData/Local/Temp') / f'soler_{browser_name}_{profile_dir.name}.db'
            shutil.copy2(candidate, tmp)
            conn = sqlite3.connect(tmp)
            for row in conn.execute("SELECT host_key,name,path,expires_utc,is_secure,encrypted_value,value FROM cookies"):
                host, name, path, expires, secure, enc_val, val = row
                if not any(d in host.lower() for d in DOMAINS): continue
                value = val
                if enc_val:
                    value = decrypt(enc_val, key)
                if not value: continue
                expires_unix = max(0, int(expires / 1_000_000) - 11644473600) if expires else 0
                results.append((host, 'TRUE' if host.startswith('.') else 'FALSE',
                                path, 'TRUE' if secure else 'FALSE', expires_unix, name, value))
            conn.close()
            tmp.unlink()
        except Exception as e:
            print(f"  [{browser_name}/{profile_dir.name}] error: {e}")
    return results


all_cookies = []
for name, path in BROWSERS:
    print(f"\n=== {name} ({path}) ===")
    if not path.exists():
        print("  [no existe]")
        continue
    c = extract(name, path)
    print(f"  {len(c)} cookies de dominios de interes")
    all_cookies.extend(c)

# Dedup
seen = set()
unique = []
for c in all_cookies:
    k = (c[0], c[5], c[2])
    if k not in seen:
        seen.add(k)
        unique.append(c)

lines = ['# Netscape HTTP Cookie File', '# SOLER extraction', '']
for host, sub, p, sec, exp, name, val in unique:
    lines.append(f"{host}\t{sub}\t{p}\t{sec}\t{exp}\t{name}\t{val}")
OUTPUT.write_text('\n'.join(lines) + '\n', encoding='utf-8')

print(f"\n[OK] {len(unique)} cookies -> {OUTPUT}")
from collections import Counter
for h, n in Counter(c[0] for c in unique).most_common():
    print(f"  {h}: {n}")
