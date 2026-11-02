"""Roles inside an organization and what each may do.

Platform super admin is a flag on the user (users.is_platform_admin), not an organization role. It lets a
person create and suspend organizations, but gives no access to any organization's data: for that they
need a membership like everyone else.
"""
OWNER = "organization_owner"
ADMIN = "organization_admin"
TRAINER = "trainer"
TRAINEE = "trainee"

ROLES = (OWNER, ADMIN, TRAINER, TRAINEE)
RANK = {TRAINEE: 1, TRAINER: 2, ADMIN: 3, OWNER: 4}

# permission -> lowest role that has it
PERMISSIONS = {
    "org.view": TRAINEE,
    "members.view": TRAINER,
    "members.manage": ADMIN,
    "invitations.manage": ADMIN,
    "org.update": ADMIN,
    "audit.view": ADMIN,
    # voice agents (phase 2)
    "training.self": TRAINEE,      # see agents assigned to me
    "agents.view": TRAINER,        # see the whole agent registry, versions and scenarios
    "agents.manage": ADMIN,        # register, configure, publish and archive agents
    # Knowledge content is more sensitive than agent metadata. Trainers can inspect library metadata;
    # only organization admins can change or read source content until a finer-grained grant model exists.
    "knowledge.view": TRAINER,
    "knowledge.content.view": ADMIN,
    "knowledge.manage": ADMIN,
    "agents.preview": TRAINER,
    "agents.provider_test": ADMIN,
    "agents.publish": ADMIN,
    "scenarios.manage": TRAINER,
    "assignments.manage": TRAINER,  # trainers may only assign to trainees and teams
    "teams.view": TRAINER,
    "teams.manage": ADMIN,
    # training sessions (phase 3)
    "training.view": TRAINER,    # every session and the usage of the organization
    "training.manage": ADMIN,    # cancel anyone's session, verify trainee phone numbers
    # training intelligence (phase 4)
    "rubrics.manage": TRAINER,     # create rubrics and publish rubric versions
    "evaluations.manage": ADMIN,   # re-run an evaluation or a reconciliation
    "recordings.view": TRAINER,    # play any session's recording (a trainee may always play their own)
    "recordings.manage": ADMIN,    # delete recordings, change recording and consent settings
}


def has_permission(role: str, permission: str) -> bool:
    need = PERMISSIONS.get(permission)
    return need is not None and RANK.get(role, 0) >= RANK[need]


def permissions_for(role: str) -> list[str]:
    return sorted(p for p in PERMISSIONS if has_permission(role, p))


def can_grant(actor_role: str, role: str) -> bool:
    """Owners can grant any role. Admins can grant admin, trainer and trainee, never owner."""
    if role not in RANK:
        return False
    if actor_role == OWNER:
        return True
    return actor_role == ADMIN and role != OWNER


def can_manage_member(actor_role: str, target_role: str) -> bool:
    """Admins cannot change or remove owners; owners can manage anyone."""
    if actor_role == OWNER:
        return True
    return actor_role == ADMIN and target_role != OWNER


def can_assign_to(actor_role: str, target_role: str) -> bool:
    """Admins and owners can assign agents to anyone in the organization. Trainers only to trainees."""
    if RANK.get(actor_role, 0) >= RANK[ADMIN]:
        return target_role in RANK
    return actor_role == TRAINER and target_role == TRAINEE
