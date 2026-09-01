from fastapi.testclient import TestClient


def test_contacts_page_is_mobile_friendly_and_public_safe(client: TestClient) -> None:
    response = client.get("/contacts")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")

    body = response.text
    assert '<meta name="viewport"' in body
    assert "Timur Shevlyakov" in body
    assert "Open-source embodied AI for agriculture." in body
    assert "https://www.linkedin.com/in/timur-shevlyakov/" in body
    assert "https://github.com/cracketus/senior-pomidor" in body
    assert 'href="/contacts.vcf"' in body

    # Contact page must not accidentally expose deployment or private-network details.
    assert "localhost" not in body
    assert "192.168." not in body
    assert "10.0." not in body
    assert "TELEMETRY_UPLOAD_TOKEN" not in body
    assert "mailto:" not in body


def test_contacts_vcard_can_be_saved(client: TestClient) -> None:
    response = client.get("/contacts.vcf")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/vcard")
    assert response.headers["content-disposition"] == 'attachment; filename="timur-shevlyakov.vcf"'
    assert "BEGIN:VCARD" in response.text
    assert "FN:Timur Shevlyakov" in response.text
    assert "https://cracketus.dev/contacts" in response.text
    assert "https://www.linkedin.com/in/timur-shevlyakov/" in response.text
    assert "https://github.com/cracketus" in response.text
    assert "END:VCARD" in response.text
