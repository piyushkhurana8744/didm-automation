"""Create safe, repeatable demo records in a local SQLite database.

Run with:
    DATABASE_URL=sqlite:///./demo.db python -m scripts.seed_demo

The script refuses non-SQLite databases so fake records cannot reach staging or production accidentally.
"""
import os

from sqlalchemy import select

from app.db import SessionLocal, init_db, utcnow
from app.saas.models import (Agent, AgentAssignment, AgentVersion, Membership, Organization, Team, TeamMember,
                             TrainingOrgLimits, TrainingScenario, User)
from app.saas.passwords import hash_password

DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "DemoPassword123!")


def one(db, model, **where):
    return db.scalars(select(model).filter_by(**where)).first()


def user(db, email: str, name: str, platform=False) -> User:
    row = one(db, User, email=email)
    if row is None:
        row = User(email=email, name=name, password_hash=hash_password(DEMO_PASSWORD), status="active",
                   is_platform_admin=platform, email_verified_at=utcnow())
        db.add(row)
        db.flush()
    elif platform:
        row.is_platform_admin = True
    return row


def main() -> int:
    url = os.getenv("DATABASE_URL", "sqlite:///./demo.db")
    if not url.startswith("sqlite"):
        raise SystemExit("Refusing to seed a non-SQLite database. Use DATABASE_URL=sqlite:///./demo.db")
    init_db(url, migrate=True)
    with SessionLocal() as db:
        admin = user(db, "demo.admin@example.com", "Demo Platform Admin", platform=True)
        owner = user(db, "owner@demo.example", "Demo Owner")
        trainee = user(db, "trainee@demo.example", "Demo Trainee")

        org = one(db, Organization, slug="demo-academy")
        if org is None:
            org = Organization(name="Demo Academy", slug="demo-academy", status="active", settings={})
            db.add(org)
            db.flush()
        for member, role in ((owner, "organization_owner"), (trainee, "trainee")):
            if one(db, Membership, organization_id=org.id, user_id=member.id) is None:
                db.add(Membership(organization_id=org.id, user_id=member.id, role=role, status="active"))

        team = one(db, Team, organization_id=org.id, name="Admissions Trainees")
        if team is None:
            team = Team(organization_id=org.id, name="Admissions Trainees",
                        description="Sample team for exploring assignments", created_by=owner.id)
            db.add(team)
            db.flush()
        if one(db, TeamMember, team_id=team.id, user_id=trainee.id) is None:
            db.add(TeamMember(organization_id=org.id, team_id=team.id, user_id=trainee.id, added_by=owner.id))

        agent = one(db, Agent, organization_id=org.id, provider_app_id="demo-sarvam-agent")
        if agent is None:
            agent = Agent(organization_id=org.id, name="Demo Admissions Coach",
                          description="UI-only demo agent; it does not place paid calls.", category="Admissions",
                          provider="sarvam", provider_app_id="demo-sarvam-agent", channels=["phone"],
                          created_by=owner.id)
            db.add(agent)
            db.flush()
        version = one(db, AgentVersion, agent_id=agent.id, internal_version=1)
        if version is None:
            version = AgentVersion(organization_id=org.id, agent_id=agent.id, internal_version=1,
                                   provider_app_version=1, status="published", published_at=utcnow(),
                                   published_by=owner.id, created_by=owner.id,
                                   configuration_snapshot={"demo": True}, variable_schema=[])
            db.add(version)
            db.flush()
            agent.published_version_id = version.id

        scenario = one(db, TrainingScenario, organization_id=org.id, name="Fee Objection Practice")
        if scenario is None:
            scenario = TrainingScenario(organization_id=org.id, agent_id=agent.id,
                name="Fee Objection Practice", description="Handle a learner concerned about course fees.",
                difficulty="beginner", persona="Interested learner comparing institutes",
                objective="Explain value and agree on a counselling follow-up.",
                opening_context="The learner asks why the program costs more than alternatives.",
                expected_behavior="Ask questions, explain value, and avoid pressure.", status="active",
                validated_version_id=version.id, agent_variables={}, created_by=owner.id)
            db.add(scenario)
            db.flush()

        if one(db, AgentAssignment, agent_id=agent.id, team_id=team.id, revoked_at=None) is None:
            db.add(AgentAssignment(organization_id=org.id, agent_id=agent.id, team_id=team.id,
                                   assigned_by=owner.id, settings={"allowed_scenario_ids": [scenario.id],
                                   "max_sessions": 3, "max_minutes_per_session": 10}))
        limits = db.get(TrainingOrgLimits, org.id)
        if limits is None:
            # Deliberately disabled: demo browsing is free and cannot trigger a paid provider call.
            db.add(TrainingOrgLimits(organization_id=org.id, enabled=False, phone_enabled=False,
                                     browser_enabled=False, evaluation_enabled=False, recording_allowed=False,
                                     updated_by=admin.id))
        db.commit()

    print("Demo data ready in demo.db")
    print("Platform admin: demo.admin@example.com")
    print("Organization owner: owner@demo.example")
    print("Trainee: trainee@demo.example")
    print(f"Password for all demo users: {DEMO_PASSWORD}")
    print("Paid phone, browser, evaluation and recording actions remain disabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
