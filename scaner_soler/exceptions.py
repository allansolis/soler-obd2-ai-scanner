"""Excepciones compartidas de Scaner Soler — sin dependencias internas."""


class SafetyError(Exception):
    """Lanzada cuando una operación viola los límites de seguridad definidos."""
    pass


class ProtocolError(Exception):
    """Error de comunicación con el vehículo / ECU."""
    pass


class ECUNotConnectedError(Exception):
    """Operación solicitada sin conexión activa con la ECU."""
    pass
