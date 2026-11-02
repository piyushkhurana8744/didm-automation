"""Password hashing and random tokens, using only the Python standard library.

Passwords use scrypt with N=2^15, r=8, p=3 (one of OWASP's recommended scrypt settings, about 32 MiB per
hash). The parameters are stored in each hash, so they can be raised later and old hashes still verify.
"""
import hashlib
import hmac
import secrets

SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 3
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=256 * 1024 * 1024, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        calc = _scrypt(password, bytes.fromhex(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc.hex(), digest)


# Verified against when the email is unknown, so a login takes the same time either way
_DUMMY_HASH = None


def dummy_verify(password: str) -> None:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_hex(8))
    verify_password(password, _DUMMY_HASH)


def password_problem(password: str) -> str | None:
    """Returns why a new password is not acceptable, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    if password.strip() != password or not password.strip():
        return "Password must not start or end with spaces."
    return None


def new_token() -> str:
    """A 256-bit random secret for cookies, invitations and reset links."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Only this SHA-256 is stored, so a database leak does not reveal usable tokens."""
    return hashlib.sha256(token.encode()).hexdigest()
