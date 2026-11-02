"""Cookie login sessions, CSRF protection and the organization access check used by every tenant route."""
import hmac
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal, utcnow
from ..security import client_ip
from .models import AuditEvent, AuthSession, Membership, Organization, User
from .passwords import new_token, token_hash
from .permissions import has_permission

SESSION_COOKIE = "didm_session"
CSRF_COOKIE = "didm_csrf"
CSRF_HEADER = "x-csrf-token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def settings_of(request: Request):
    return request.app.state.settings


def ip_of(request: Request) -> str:
    return client_ip(request, settings_of(request).trust_proxy_headers)


def audit(db: Session, request: Request | None, action: str, actor: User | None = None,
          organization_id: str | None = None, target_type: str | None = None, target_id: str | None = None,
          details: dict | None = None):
    """Adds an audit row to the current transaction. Never put secrets in details."""
    db.add(AuditEvent(organization_id=organization_id, actor_user_id=actor.id if actor else None, action=action,
                      target_type=target_type, target_id=target_id, details=details or {},
                      ip=ip_of(request) if request else None))


# ---------- sessions ----------
def start_session(db: Session, request: Request, user: User, response) -> AuthSession:
    s = settings_of(request)
    token, csrf = new_token(), new_token()
    now = utcnow()
    first = db.scalars(select(Membership).join(Organization, Organization.id == Membership.organization_id).where(
        Membership.user_id == user.id, Membership.status == "active", Organization.status == "active")
        .order_by(Membership.created_at)).first()
    row = AuthSession(token_hash=token_hash(token), csrf_hash=token_hash(csrf), user_id=user.id,
                      active_organization_id=first.organization_id if first else None,
                      ip=ip_of(request), user_agent=(request.headers.get("user-agent") or "")[:300],
                      created_at=now, last_seen_at=now, expires_at=now + timedelta(hours=s.session_ttl_hours))
    db.add(row)
    max_age = s.session_ttl_hours * 3600
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=s.cookie_secure,
                        samesite="lax", path="/")
    # Readable by the page so it can echo it in the X-CSRF-Token header (double-submit, bound to the session)
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=s.cookie_secure,
                        samesite="lax", path="/")
    return row


def clear_cookies(request: Request, response):
    s = settings_of(request)
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=s.cookie_secure, samesite="lax")


def revoke_user_sessions(db: Session, user_id: str, keep_session_id: str | None = None):
    for row in db.scalars(select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))):
        if row.id != keep_session_id:
            row.revoked_at = utcnow()


@dataclass
class Auth:
    user: User
    session: AuthSession


def _load_auth(request: Request, db: Session) -> Auth | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    row = db.scalars(select(AuthSession).where(AuthSession.token_hash == token_hash(token))).first()
    now = utcnow()
    s = settings_of(request)
    if (row is None or row.revoked_at is not None or row.expires_at <= now
            or row.last_seen_at <= now - timedelta(hours=s.session_idle_hours)):
        return None
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    if now - row.last_seen_at > timedelta(minutes=5):
        row.last_seen_at = now
        db.commit()
    return Auth(user=user, session=row)


def current_auth(request: Request, db: Session = Depends(get_db)) -> Auth:
    auth = _load_auth(request, db)
    if auth is None:
        raise HTTPException(status_code=401, detail="Please log in.")
    if request.method in UNSAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not hmac.compare_digest(token_hash(sent), auth.session.csrf_hash):
            raise HTTPException(status_code=403, detail="Missing or wrong CSRF token.")
    return auth


def platform_admin(auth: Auth = Depends(current_auth)) -> Auth:
    if not auth.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrators only.")
    return auth


# ---------- organization access ----------
@dataclass
class OrgContext:
    auth: Auth
    org: Organization
    membership: Membership

    @property
    def user(self) -> User:
        return self.auth.user

    @property
    def role(self) -> str:
        return self.membership.role


def org_access(permission: str):
    """Dependency for routes under /organizations/{org_id}.

    The org id in the path only says which organization the caller wants. Access comes from the
    caller's own active membership, looked up on the server. Unknown organizations and organizations the
    caller does not belong to both answer 404, so ids cannot be probed.
    """
    def dep(org_id: str, auth: Auth = Depends(current_auth), db: Session = Depends(get_db)) -> OrgContext:
        m = db.scalars(select(Membership).where(Membership.organization_id == org_id,
                                                Membership.user_id == auth.user.id,
                                                Membership.status == "active")).first()
        org = db.get(Organization, org_id) if m else None
        if m is None or org is None:
            raise HTTPException(status_code=404, detail="Organization not found.")
        if org.status != "active":
            raise HTTPException(status_code=403, detail="This organization is suspended.")
        if not has_permission(m.role, permission):
            raise HTTPException(status_code=403, detail="Your role does not allow this.")
        return OrgContext(auth=auth, org=org, membership=m)
    return dep


def scoped_get(db: Session, model, org_id: str, obj_id: str):
    """Loads a tenant-owned row only if it belongs to org_id; otherwise 404. Use for every id from a client."""
    obj = db.scalars(select(model).where(model.id == obj_id, model.organization_id == org_id)).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Not found.")
    return obj
