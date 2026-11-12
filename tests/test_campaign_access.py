"""Excel calling follows active phone-agent assignments."""
from tests.test_agents import world, publish_agent, assign  # noqa: F401
from tests.test_saas import saas  # noqa: F401


def test_assigned_trainee_can_upload_and_only_select_assigned_agents(world):
    a = world.a
    agent, _ = publish_agent(a)
    other, _ = publish_agent(a, app_id="other-phone")
    base = f"{a.base}/calling-campaign"
    assert a.trainee.get(base).status_code == 403
    result = assign(a, a.owner, [agent], [a.user_id("trainee@alpha.in")])
    assert result.status_code == 201, result.text
    assignment = result.json()["created"][0]["id"]
    status = a.trainee.get(base)
    assert status.status_code == 200, status.text
    assert [item["id"] for item in status.json()["agents"]] == [agent]
    assert a.trainee.get(f"{base}/sample.xlsx").status_code == 200
    uploaded = a.trainee.post(f"{base}/upload", content=b"name,phone\nRiya,9876543210\n",
                             headers={"X-Upload-Filename": "leads.csv"})
    assert uploaded.status_code == 200, uploaded.text
    assert a.trainee.post(f"{base}/start", {"agent_id": other}).status_code == 422
    assert a.trainee2.post(f"{base}/stop").status_code == 403
    assert a.owner.post(f"{a.base}/assignments/{assignment}/revoke").status_code == 200
    assert a.trainee.get(base).status_code == 403
    assert a.trainee.post(f"{base}/resume").status_code == 403
    assert a.owner.get(base).status_code == 200


def test_browser_only_assignment_does_not_allow_excel_calling(world):
    a = world.a
    agent, _ = publish_agent(a, channels=["browser"])
    assert assign(a, a.owner, [agent], [a.user_id("trainee@alpha.in")]).status_code == 201
    assert a.trainee.get(f"{a.base}/calling-campaign").status_code == 403
