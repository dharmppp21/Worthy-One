from datetime import datetime, timezone


class TestRunbookCRUD:
    """End-to-end test: runbook create, read, update, delete, list, search."""

    def test_create_runbook(self, client, reset_store):
        payload = {
            "tenant_id": "demo-company",
            "service_name": "checkout-service",
            "title": "Checkout outage playbook",
            "description": "Steps to recover checkout-service",
            "steps": ["Check payment-service", "Check inventory-service", "Escalate if needed"],
        }
        resp = client.post("/runbooks", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "demo-company"
        assert data["service_name"] == "checkout-service"
        assert data["title"] == "Checkout outage playbook"
        assert data["description"] == "Steps to recover checkout-service"
        assert data["steps"] == ["Check payment-service", "Check inventory-service", "Escalate if needed"]
        assert "id" in data
        assert "created_at" in data

    def test_list_runbooks(self, client, reset_store):
        for title in ["Runbook A", "Runbook B"]:
            client.post("/runbooks", json={
                "tenant_id": "demo-company",
                "service_name": "checkout-service",
                "title": title,
                "description": f"Desc for {title}",
                "steps": [],
            })

        resp = client.get("/runbooks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        titles = {rb["title"] for rb in data}
        assert titles == {"Runbook A", "Runbook B"}

    def test_list_runbooks_filtered_by_service(self, client, reset_store):
        client.post("/runbooks", json={
            "tenant_id": "demo-company",
            "service_name": "checkout-service",
            "title": "Checkout RB",
            "description": "desc",
            "steps": [],
        })
        client.post("/runbooks", json={
            "tenant_id": "demo-company",
            "service_name": "payment-service",
            "title": "Payment RB",
            "description": "desc",
            "steps": [],
        })

        checkout_only = client.get("/runbooks?service_name=checkout-service").json()
        assert len(checkout_only) == 1
        assert checkout_only[0]["title"] == "Checkout RB"

    def test_get_runbook_by_id(self, client, reset_store):
        created = client.post("/runbooks", json={
            "tenant_id": "demo-company",
            "service_name": "checkout-service",
            "title": "Specific RB",
            "description": "desc",
            "steps": ["Step 1"],
        }).json()

        resp = client.get(f"/runbooks/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Specific RB"

    def test_get_runbook_not_found_returns_404(self, client, reset_store):
        resp = client.get("/runbooks/nonexistent-id")
        assert resp.status_code == 404

    def test_update_runbook(self, client, reset_store):
        created = client.post("/runbooks", json={
            "tenant_id": "demo-company",
            "service_name": "checkout-service",
            "title": "Old Title",
            "description": "Old desc",
            "steps": ["Old step"],
        }).json()

        patch = client.patch(f"/runbooks/{created['id']}", json={
            "title": "New Title",
            "description": "New desc",
            "steps": ["New step"],
        })
        assert patch.status_code == 200
        updated = patch.json()
        assert updated["title"] == "New Title"
        assert updated["description"] == "New desc"
        assert updated["steps"] == ["New step"]
        assert updated["updated_at"] >= created["updated_at"]

    def test_update_runbook_not_found_returns_404(self, client, reset_store):
        resp = client.patch("/runbooks/nonexistent-id", json={"title": "New"})
        assert resp.status_code == 404

    def test_delete_runbook(self, client, reset_store):
        created = client.post("/runbooks", json={
            "tenant_id": "demo-company",
            "service_name": "checkout-service",
            "title": "To Delete",
            "description": "desc",
            "steps": [],
        }).json()

        delete = client.delete(f"/runbooks/{created['id']}")
        assert delete.status_code == 200
        assert delete.json()["deleted"] is True

        # Verify it's gone
        assert client.get(f"/runbooks/{created['id']}").status_code == 404

    def test_delete_runbook_not_found_returns_404(self, client, reset_store):
        resp = client.delete("/runbooks/nonexistent-id")
        assert resp.status_code == 404


class TestRunbookSearch:
    """End-to-end test: keyword search finds runbooks."""

    def test_search_finds_runbook_by_title(self, client, reset_store):
        client.post("/runbooks", json={
            "tenant_id": "demo-company",
            "service_name": "checkout-service",
            "title": "Checkout outage playbook",
            "description": "desc",
            "steps": [],
        })
        client.post("/runbooks", json={
            "tenant_id": "demo-company",
            "service_name": "payment-service",
            "title": "Payment latency runbook",
            "description": "desc",
            "steps": [],
        })

        resp = client.get("/search?q=checkout")
        assert resp.status_code == 200
        data = resp.json()
        results = data["results"]
        assert any(r["type"] == "runbook" and "checkout" in r["title"].lower() for r in results)

    def test_search_finds_runbook_by_description(self, client, reset_store):
        client.post("/runbooks", json={
            "tenant_id": "demo-company",
            "service_name": "checkout-service",
            "title": "RB title",
            "description": "This runbook handles database connection failures",
            "steps": [],
        })

        resp = client.get("/search?q=database")
        assert resp.status_code == 200
        data = resp.json()
        results = [r for r in data["results"] if r["type"] == "runbook"]
        assert len(results) >= 1
        assert any("database" in r["summary"] for r in results)

    def test_search_finds_runbook_by_service_name(self, client, reset_store):
        client.post("/runbooks", json={
            "tenant_id": "demo-company",
            "service_name": "fraud-service",
            "title": "Fraud runbook",
            "description": "desc",
            "steps": [],
        })

        resp = client.get("/search?q=fraud-service")
        assert resp.status_code == 200
        data = resp.json()
        results = [r for r in data["results"] if r["type"] == "runbook"]
        assert any(r["service_name"] == "fraud-service" for r in results)
