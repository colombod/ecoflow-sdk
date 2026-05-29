"""Tests for src/ecoflow/__init__.py and src/ecoflow/transport/__init__.py.

RED-first tests for task-11-package-init-files.
"""


class TestPackageInit:
    """Verify src/ecoflow/__init__.py defines __version__."""

    def test_version_attribute_exists(self) -> None:
        import ecoflow

        assert hasattr(ecoflow, "__version__"), "ecoflow must define __version__"

    def test_version_value(self) -> None:
        import ecoflow

        assert ecoflow.__version__ == "0.1.0"


class TestTransportInit:
    """Verify src/ecoflow/transport/__init__.py exports the expected symbols."""

    def test_rest_client_importable_from_transport(self) -> None:
        from ecoflow.transport import RestTransport

        assert RestTransport is not None

    def test_mqtt_client_importable_from_transport(self) -> None:
        from ecoflow.transport import MqttTransport

        assert MqttTransport is not None

    def test_mqtt_credentials_importable_from_transport(self) -> None:
        from ecoflow.transport import MqttCredentials

        assert MqttCredentials is not None

    def test_transport_all_contains_expected_symbols(self) -> None:
        import ecoflow.transport as transport

        assert hasattr(transport, "__all__"), "transport must define __all__"
        all_names = transport.__all__
        assert "RestTransport" in all_names
        assert "MqttTransport" in all_names
        assert "MqttCredentials" in all_names

    def test_transport_all_exact_membership(self) -> None:
        import ecoflow.transport as transport

        assert set(transport.__all__) == {
            "RestTransport",
            "MqttTransport",
            "MqttCredentials",
        }

    def test_rest_client_is_correct_class(self) -> None:
        from ecoflow.transport import RestTransport
        from ecoflow.transport.rest import RestTransport as OrigRestTransport

        assert RestTransport is OrigRestTransport

    def test_mqtt_client_is_correct_class(self) -> None:
        from ecoflow.transport import MqttTransport
        from ecoflow.transport.mqtt import MqttTransport as OrigMqttTransport

        assert MqttTransport is OrigMqttTransport

    def test_mqtt_credentials_is_correct_class(self) -> None:
        from ecoflow.transport import MqttCredentials
        from ecoflow.transport.mqtt import MqttCredentials as OrigMqttCredentials

        assert MqttCredentials is OrigMqttCredentials
