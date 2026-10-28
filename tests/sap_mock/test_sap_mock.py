import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.sap_mock import SqliteSapMock, get_sap, router

BASE = {
    "CaseId": "CASE-001",
    "Material": "0169-4524-14",
    "Quantity": 300,
    "Unit": "carton",
    "Supplier": "SUP-003",
}
PRICED = {**BASE, "NetPrice": 1240.0, "Currency": "USD"}


@pytest.fixture
def client(tmp_path):
    sap = SqliteSapMock(tmp_path / "sap.db")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_sap] = lambda: sap
    yield TestClient(app)
    sap.close()


@pytest.mark.parametrize(
    "path, body, number, doc_type",
    [
        ("/sap/rfq", BASE, "RFQ-6000001", "RFQ"),
        ("/sap/supplier-quotation", PRICED, "QTN-7000001", "SupplierQuotation"),
        ("/sap/purchase-order", PRICED, "PO-4500001", "PurchaseOrder"),
    ],
)
def test_create_returns_document_number(client, path, body, number, doc_type):
    response = client.post(path, json={"d": body})
    assert response.status_code == 201
    assert response.json()["DocumentNumber"] == number
    assert response.json()["DocumentType"] == doc_type


def test_numbers_increment_per_type(client):
    client.post("/sap/rfq", json={"d": BASE})
    second = client.post("/sap/rfq", json={"d": BASE}).json()
    po = client.post("/sap/purchase-order", json={"d": PRICED}).json()
    assert second["DocumentNumber"] == "RFQ-6000002"
    assert po["DocumentNumber"] == "PO-4500001"


@pytest.mark.parametrize(
    "path, body, missing",
    [
        ("/sap/rfq", {k: v for k, v in BASE.items() if k != "Material"}, ["Material"]),
        ("/sap/supplier-quotation", BASE, ["NetPrice", "Currency"]),
        ("/sap/purchase-order", {**PRICED, "Supplier": ""}, ["Supplier"]),
    ],
)
def test_rejects_missing_keys(client, path, body, missing):
    response = client.post(path, json={"d": body})
    assert response.status_code == 422
    assert response.json()["detail"]["missing"] == missing
    assert client.get("/sap/documents").json() == []


def test_rejects_body_without_d_wrapper(client):
    response = client.post("/sap/rfq", json=BASE)
    assert response.status_code == 422


def test_list_documents_filters_by_case(client):
    client.post("/sap/rfq", json={"d": BASE})
    client.post("/sap/purchase-order", json={"d": PRICED})
    client.post("/sap/rfq", json={"d": {**BASE, "CaseId": "CASE-002"}})

    case_1 = client.get("/sap/documents", params={"case_id": "CASE-001"}).json()
    assert [d["DocumentNumber"] for d in case_1] == ["RFQ-6000001", "PO-4500001"]
    assert case_1[1]["Payload"]["NetPrice"] == 1240.0
    assert len(client.get("/sap/documents").json()) == 3


def test_persists_across_reopen(tmp_path):
    path = tmp_path / "sap.db"
    sap = SqliteSapMock(path)
    sap.create_document("rfq", BASE)
    sap.close()

    reopened = SqliteSapMock(path)
    assert reopened.create_document("rfq", BASE)["DocumentNumber"] == "RFQ-6000002"
    assert len(reopened.list_documents("CASE-001")) == 2
    reopened.close()


def test_case_id_is_parameterised_not_interpolated(client):
    client.post("/sap/rfq", json={"d": BASE})
    response = client.get("/sap/documents", params={"case_id": "x' OR '1'='1"})
    assert response.json() == []
