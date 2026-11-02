"""Integration tests for admin staff auth and RBAC."""

from app.modules.admin.permissions import ROLE_CREATE, STAFF_READ
from tests.conftest import TEST_ADMIN_PHONE, TEST_OTP


class TestStaffAuth:
    async def test_super_admin_login(self, api_client, super_admin):
        req = await api_client.post(
            "/api/v1/admin/auth/login/request-otp",
            json={"phone": TEST_ADMIN_PHONE},
        )
        assert req.status_code == 200

        verify = await api_client.post(
            "/api/v1/admin/auth/login/verify-otp",
            json={"phone": TEST_ADMIN_PHONE, "otp": TEST_OTP},
        )
        assert verify.status_code == 200
        data = verify.json()
        assert data["staff"]["is_super_admin"] is True
        assert ROLE_CREATE in data["staff"]["permissions"]

    async def test_inactive_staff_cannot_request_otp(self, api_client, admin_headers):
        create = await api_client.post(
            "/api/v1/admin/staff",
            headers=admin_headers,
            json={
                "full_name": "Jane Doe",
                "email": "jane@ghtrust.com",
                "phone": "08098765432",
                "role_id": None,
            },
        )
        assert create.status_code == 201
        assert create.json()["status"] == "inactive"

        otp = await api_client.post(
            "/api/v1/admin/auth/login/request-otp",
            json={"phone": "08098765432"},
        )
        assert otp.status_code == 403

    async def test_customer_token_cannot_access_admin(self, api_client, registered_customer):
        token = registered_customer["access_token"]
        res = await api_client.get(
            "/api/v1/admin/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 401


class TestRoleManagement:
    async def test_create_and_list_roles(self, api_client, admin_headers):
        created = await api_client.post(
            "/api/v1/admin/roles",
            headers=admin_headers,
            json={
                "name": "Loan Officer",
                "description": "Reviews loan applications",
                "permissions": [STAFF_READ],
            },
        )
        assert created.status_code == 201
        assert created.json()["name"] == "Loan Officer"

        listed = await api_client.get("/api/v1/admin/roles", headers=admin_headers)
        assert listed.status_code == 200
        names = {r["name"] for r in listed.json()}
        assert "Loan Officer" in names
        assert "Super Admin" in names


class TestStaffManagement:
    async def test_create_activate_and_login_staff(self, api_client, admin_headers):
        role = await api_client.post(
            "/api/v1/admin/roles",
            headers=admin_headers,
            json={"name": "Teller", "permissions": [STAFF_READ]},
        )
        role_id = role.json()["id"]

        staff = await api_client.post(
            "/api/v1/admin/staff",
            headers=admin_headers,
            json={
                "full_name": "John Teller",
                "email": "john@ghtrust.com",
                "phone": "08055554444",
                "role_id": role_id,
            },
        )
        assert staff.status_code == 201
        staff_id = staff.json()["id"]
        assert staff.json()["status"] == "inactive"

        activated = await api_client.post(
            f"/api/v1/admin/staff/{staff_id}/activate",
            headers=admin_headers,
        )
        assert activated.status_code == 200
        assert activated.json()["status"] == "active"

        await api_client.post(
            "/api/v1/admin/auth/login/request-otp",
            json={"phone": "08055554444"},
        )
        login = await api_client.post(
            "/api/v1/admin/auth/login/verify-otp",
            json={"phone": "08055554444", "otp": TEST_OTP},
        )
        assert login.status_code == 200
        assert login.json()["staff"]["full_name"] == "John Teller"

    async def test_cannot_activate_without_role(self, api_client, admin_headers):
        staff = await api_client.post(
            "/api/v1/admin/staff",
            headers=admin_headers,
            json={
                "full_name": "No Role",
                "email": "norole@ghtrust.com",
                "phone": "08011112222",
            },
        )
        staff_id = staff.json()["id"]
        res = await api_client.post(
            f"/api/v1/admin/staff/{staff_id}/activate",
            headers=admin_headers,
        )
        assert res.status_code == 422

    async def test_deactivate_staff_blocks_login(self, api_client, admin_headers):
        role = await api_client.post(
            "/api/v1/admin/roles",
            headers=admin_headers,
            json={"name": "Ops", "permissions": [STAFF_READ]},
        )
        staff = await api_client.post(
            "/api/v1/admin/staff",
            headers=admin_headers,
            json={
                "full_name": "Ops User",
                "email": "ops@ghtrust.com",
                "phone": "08033334444",
                "role_id": role.json()["id"],
            },
        )
        staff_id = staff.json()["id"]
        await api_client.post(f"/api/v1/admin/staff/{staff_id}/activate", headers=admin_headers)
        await api_client.post(f"/api/v1/admin/staff/{staff_id}/deactivate", headers=admin_headers)

        otp = await api_client.post(
            "/api/v1/admin/auth/login/request-otp",
            json={"phone": "08033334444"},
        )
        assert otp.status_code == 403


class TestAdminDashboard:
    async def test_dashboard_requires_loan_read(self, api_client, admin_headers, db_session):
        from app.modules.loans.service import seed_loan_products

        await seed_loan_products(db_session)
        await db_session.commit()

        res = await api_client.get("/api/v1/admin/dashboard", headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        assert "total_applications" in data
        assert "status_counts" in data
        assert "recent_applications" in data
        assert "daily_submissions" in data
        assert len(data["daily_submissions"]) == 7
        assert "demographics" in data
        assert "gender" in data["demographics"]


class TestAdminCustomers:
    async def test_list_and_get_customers(self, api_client, admin_headers, registered_customer):
        listing = await api_client.get("/api/v1/admin/customers", headers=admin_headers)
        assert listing.status_code == 200
        customers = listing.json()
        assert isinstance(customers, list)
        assert len(customers) >= 1

        customer_id = registered_customer["customer"]["id"]
        detail = await api_client.get(f"/api/v1/admin/customers/{customer_id}", headers=admin_headers)
        assert detail.status_code == 200
        data = detail.json()
        assert data["id"] == customer_id
        assert data["full_name"]
        assert "loan_applications" in data
        assert "stats" in data

    async def test_customers_require_loan_read(self, api_client, registered_customer):
        token = registered_customer["access_token"]
        res = await api_client.get(
            "/api/v1/admin/customers",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 401


class TestAdminSettings:
    async def test_settings_snapshot(self, api_client, admin_headers):
        res = await api_client.get("/api/v1/admin/settings", headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        assert "default_branch" in data
        assert "app_env" in data

    async def test_branches_list(self, api_client, admin_headers, registered_customer):
        res = await api_client.get("/api/v1/admin/settings/branches", headers=admin_headers)
        assert res.status_code == 200
        branches = res.json()
        assert isinstance(branches, list)
        assert len(branches) >= 1

    async def test_toggle_loan_product(self, api_client, admin_headers, db_session):
        from app.modules.loans.service import seed_loan_products

        await seed_loan_products(db_session)
        await db_session.commit()

        listing = await api_client.get("/api/v1/admin/loans/products", headers=admin_headers)
        product = next(p for p in listing.json() if p["code"] == "lpo_invoice_financing")
        assert product["is_active"] is True  # on since the website catalogue (migration 029)
        off = await api_client.patch(
            "/api/v1/admin/loans/products/lpo_invoice_financing", headers=admin_headers, json={"is_active": False}
        )
        assert off.status_code == 200, off.text

        # LPO has no approval workflow yet: switching it on would strand its applications.
        blocked = await api_client.patch(
            "/api/v1/admin/loans/products/lpo_invoice_financing",
            headers=admin_headers,
            json={"is_active": True},
        )
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "WORKFLOW_REQUIRED"

        from app.modules.loans.workflow_seed import seed_workflow_roles

        roles = await seed_workflow_roles(db_session)
        await db_session.commit()
        draft = await api_client.post(
            "/api/v1/admin/loans/products/lpo_invoice_financing/workflows",
            headers=admin_headers,
            json={"stages": [{"name": "Review", "approver_role_id": roles["Loan Officer"].id}]},
        )
        assert draft.status_code == 201, draft.text
        await api_client.post(f"/api/v1/admin/loans/workflows/{draft.json()['id']}/publish", headers=admin_headers)

        toggle = await api_client.patch(
            "/api/v1/admin/loans/products/lpo_invoice_financing",
            headers=admin_headers,
            json={"is_active": True},
        )
        assert toggle.status_code == 200
        assert toggle.json()["is_active"] is True
