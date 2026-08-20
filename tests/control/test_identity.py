from ip_risk_agent.application.process_change import change_event_id_for
from ip_risk_agent.core.artifacts import artifact_id_for
from ip_risk_agent.core.common import stable_key
from ip_risk_agent.core.risk import license_risk_key, patent_risk_key


def test_stable_key_encoding_has_no_delimiter_ambiguity() -> None:
    assert stable_key("test", ("a|b", "c")) != stable_key("test", ("a", "b|c"))


def test_change_and_artifact_ids_are_deterministic_and_namespaced() -> None:
    assert change_event_id_for("fingerprint") == change_event_id_for("fingerprint")
    assert artifact_id_for("source-workspace", "artifact") == artifact_id_for(
        "source-workspace", "artifact"
    )
    assert change_event_id_for("same") != artifact_id_for("same", "same")


def test_artifact_identity_does_not_include_mount_alias() -> None:
    before_rename = artifact_id_for("source-workspace", "provider-stable-id")
    after_rename = artifact_id_for("source-workspace", "provider-stable-id")
    assert before_rename == after_rename


def test_patent_risk_identity_is_stable_and_artifact_scoped() -> None:
    key = patent_risk_key("artifact-1", "KR102026000001")
    assert key == patent_risk_key("artifact-1", "KR102026000001")
    assert key != patent_risk_key("artifact-2", "KR102026000001")


def test_license_risk_identity_distinguishes_version_and_unresolved_state() -> None:
    unresolved = license_risk_key("artifact-1", "PYPI", "requests", None, "Apache-2.0")
    resolved = license_risk_key(
        "artifact-1", "PYPI", "requests", "2.32.0", "Apache-2.0"
    )
    marker_like_version = license_risk_key(
        "artifact-1", "PYPI", "requests", "not-applicable", "Apache-2.0"
    )

    assert unresolved != resolved
    assert unresolved != marker_like_version
