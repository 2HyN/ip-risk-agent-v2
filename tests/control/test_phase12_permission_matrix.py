from __future__ import annotations

import asyncio
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from ip_risk_agent.application.auth import GoogleOidcIdentity
from ip_risk_agent.core.auth import User
from ip_risk_agent.core.memberships import (
    Membership,
    MembershipRole,
    MembershipStatus,
    membership_id_for,
)
from test_control_api import NOW, build_api, login


@pytest.mark.parametrize(
    ("role", "review_status", "admin_status", "history_status"),
    [
        (MembershipRole.OWNER, 404, 201, 200),
        (MembershipRole.SOURCE_MANAGER, 404, 403, 403),
        (MembershipRole.RISK_REVIEWER, 404, 403, 403),
        (MembershipRole.VIEWER, 403, 403, 403),
    ],
)
def test_control_api_permission_matrix_matches_product_capabilities(
    role: MembershipRole,
    review_status: int,
    admin_status: int,
    history_status: int,
) -> None:
    app, store, oidc = build_api()
    with ExitStack() as stack:
        owner_client = stack.enter_context(TestClient(app))
        owner_id, owner_csrf = login(owner_client)
        created = owner_client.post(
            "/api/v1/workspaces",
            headers={"X-CSRF-Token": owner_csrf},
            json={"name": "Permission matrix"},
        )
        assert created.status_code == 201
        vws_id = created.json()["id"]

        if role is MembershipRole.OWNER:
            client = owner_client
            csrf = owner_csrf
        else:
            role_name = role.value.casefold()
            user_id = f"user-{role_name}"
            subject = f"google-{role_name}"
            email = f"{role_name}@example.com"

            async def seed_member() -> None:
                async with store() as uow:
                    await uow.users.add(
                        User(user_id, subject, email, role.value, NOW, NOW)
                    )
                    await uow.memberships.add(
                        Membership(
                            membership_id_for(vws_id, user_id),
                            vws_id,
                            user_id,
                            role,
                            MembershipStatus.ACTIVE,
                            owner_id,
                            NOW,
                            NOW,
                        )
                    )
                    await uow.commit()

            asyncio.run(seed_member())
            oidc.identity = GoogleOidcIdentity(
                subject=subject,
                email=email,
                email_verified=True,
                display_name=role.value,
            )
            client = stack.enter_context(TestClient(app))
            logged_in_id, csrf = login(client)
            assert logged_in_id == user_id

        headers = {"X-CSRF-Token": csrf}
        assert client.get(f"/api/v1/workspaces/{vws_id}").status_code == 200
        current_membership = client.get(
            f"/api/v1/workspaces/{vws_id}/membership"
        )
        assert current_membership.status_code == 200
        assert current_membership.json()["role"] == role.value
        assert client.get(f"/api/v1/workspaces/{vws_id}/risks").status_code == 200
        assert client.get(f"/api/v1/workspaces/{vws_id}/security").status_code == 200

        review = client.patch(
            f"/api/v1/workspaces/{vws_id}/risks/missing-risk/review",
            headers=headers,
            json={
                "expected_review_version": 0,
                "disposition": "MONITORING",
                "comment": None,
            },
        )
        assert review.status_code == review_status

        invitation = client.post(
            f"/api/v1/workspaces/{vws_id}/members/invitations",
            headers=headers,
            json={
                "email": f"invite-{role.value.casefold()}@example.com",
                "role": "VIEWER",
            },
        )
        assert invitation.status_code == admin_status
        assert client.get(f"/api/v1/workspaces/{vws_id}/activity").status_code == (
            history_status
        )

        policy = client.put(
            f"/api/v1/workspaces/{vws_id}/security/ipriskignore",
            headers=headers,
            json={
                "expected_policy_version": "security-v1",
                "global_ignore_text": "/generated/**\n",
            },
        )
        assert policy.status_code == (200 if role is MembershipRole.OWNER else 403)
